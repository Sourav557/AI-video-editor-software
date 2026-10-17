"""Worker: render_edl — render the user's timeline edit (Slice 9, keyframes in Slice 11).

Takes an explicit block list (the Filmora-style timeline state):
  blocks: [{id, srcStart, srcEnd, speed, muted, keyframes?}]
Renders each block (trim + speed + optional mute + caption burn with
speed-scaled timestamps), concatenates, normalizes loudness.
Blocks with keyframes render on a transparent canvas with per-frame
scale / rotation / x-y offset / opacity, then overlay centered.
Slice 14: blocks may also carry speed_ramps (piecewise-constant speed
profile, t in source timebase), reversed (backward playback), and freeze
(inserted silent still). Such blocks render as multiple pieces that are
concatenated into the block's segment; the plain path is unchanged.
Output: edit.mp4 + edit_edl.json. Idempotent.
"""
from __future__ import annotations

import math
import os
import re
import shutil
import subprocess

from ..projects import get_video_path, load_json, project_dir, save_json
from .caption import _esc, _pick_font, _srt_time


def _build_srt_scaled(words: list[dict], src_start: float, src_end: float,
                      speed: float) -> str:
    """Caption lines for one block; timestamps scaled into the block's output time."""
    in_range = [w for w in words if w["end"] > src_start and w["start"] < src_end]
    lines, cur = [], []
    for w in in_range:
        text = " ".join(x["word"] for x in cur + [w]).strip()
        if len(text) > 40 and cur:
            lines.append((cur[0]["start"], cur[-1]["end"],
                          " ".join(x["word"] for x in cur).strip()))
            cur = [w]
        else:
            cur = cur + [w]
    if cur:
        lines.append((cur[0]["start"], cur[-1]["end"],
                      " ".join(x["word"] for x in cur).strip()))
    out = []
    for i, (s, e, t) in enumerate(lines, 1):
        rs, re_ = (s - src_start) / speed, (e - src_start) / speed
        out.append(f"{i}\n{_srt_time(max(0, rs))} --> {_srt_time(re_)}\n{t}\n")
    return "\n".join(out)


def _atempo(speed: float) -> str:
    """Chain atempo filters (each supports 0.5–2.0)."""
    parts = []
    s = speed
    while s > 2.0:
        parts.append("atempo=2.0")
        s /= 2.0
    while s < 0.5:
        parts.append("atempo=0.5")
        s /= 0.5
    parts.append(f"atempo={s:.4f}")
    return ",".join(parts)


def _font_file() -> str | None:
    """Resolve a bold TTF with Latin coverage for drawtext (cross-platform)."""
    import os
    fc = shutil.which("fc-list")
    if fc:
        # try known Latin families first — a bare ":style=Bold" query can
        # return a CJK/symbol font whose glyphs render as tofu boxes
        for family in ("DejaVu Sans", "Liberation Sans", "Noto Sans", "Arial"):
            try:
                out = subprocess.run(
                    [fc, "--format=%{file}\n", f"{family}:style=Bold"],
                    capture_output=True, text=True, timeout=15).stdout
                for line in out.splitlines():
                    line = line.strip()
                    if line.lower().endswith((".ttf", ".otf")):
                        return line
            except Exception:
                pass
    cands = [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "C:/Windows/Fonts/arialbd.ttf",
    ]
    return next((c for c in cands if os.path.exists(c)), None)


# ---- Slice 11: keyframed transforms (x, y, scale, rot, op) ----
# Keyframe times are seconds relative to the block's output-time start
# (after speed is applied), matching the `t` the ffmpeg filters see.

_KF_PROPS = ("x", "y", "scale", "rot", "op")
_KF_DEFAULTS = {"x": 0.0, "y": 0.0, "scale": 1.0, "rot": 0.0, "op": 1.0}


def _fmt_num(v: float) -> str:
    s = f"{float(v):.6f}"
    return s.rstrip("0").rstrip(".") if "." in s else s


def _clean_keyframes(raw, dur: float) -> dict | None:
    """Sanitize block['keyframes'] -> {prop: [(t, v), ...]} or None.

    Times clamped to [0, dur], sorted, deduped (last wins). op clamped to
    [0, 1], scale floored at 0.01. Returns None when nothing usable.
    """
    if not isinstance(raw, dict):
        return None
    out = {}
    for prop in _KF_PROPS:
        ks = raw.get(prop) or []
        if not isinstance(ks, list):
            continue
        seen: dict[float, float] = {}
        for k in ks:
            if not isinstance(k, dict):
                continue
            try:
                t = min(max(float(k.get("t", 0.0)), 0.0), dur)
                v = float(k.get("v", _KF_DEFAULTS[prop]))
            except (TypeError, ValueError):
                continue
            if prop == "op":
                v = min(max(v, 0.0), 1.0)
            elif prop == "scale":
                v = max(v, 0.01)
            seen[round(t, 3)] = v
        if seen:
            out[prop] = sorted(seen.items())
    return out or None


def _pw_expr(pts: list[tuple[float, float]] | None, default: float,
             t_var: str = "t") -> str:
    """Nested if() chain: linear interpolation between keyframes in `t_var`.

    Before the first keyframe holds the first value, after the last holds
    the last. Commas are pre-escaped (\\,) for embedding in -vf strings.
    """
    ks = sorted(pts or [], key=lambda p: p[0])
    if not ks:
        return _fmt_num(default)
    expr = _fmt_num(ks[-1][1])
    for (t0, v0), (t1, v1) in reversed(list(zip(ks, ks[1:]))):
        t0s, t1s, v0s, v1s = _fmt_num(t0), _fmt_num(t1), _fmt_num(v0), _fmt_num(v1)
        seg = v1s if abs(t1 - t0) < 1e-9 else \
            f"{v0s}+({v1s}-{v0s})*({t_var}-{t0s})/({t1s}-{t0s})"
        expr = f"if(lt({t_var}\\,{t1s})\\,{seg}\\,{expr})"
    return f"if(lt({t_var}\\,{_fmt_num(ks[0][0])})\\,{_fmt_num(ks[0][1])}\\,{expr})"


def _source_wh(video) -> tuple[int, int]:
    """Source video dimensions (ffprobe, once per render job)."""
    ffprobe = shutil.which("ffprobe")
    pr = subprocess.run([ffprobe, "-v", "error", "-select_streams", "v:0",
                         "-show_entries", "stream=width,height",
                         "-of", "csv=p=0", str(video)],
                        capture_output=True, text=True, check=True)
    w, h = pr.stdout.strip().split(",")[:2]
    return int(w), int(h)


def _source_has_audio(video) -> bool:
    """True if the source video has at least one audio stream (ffprobe, once per job)."""
    ffprobe = shutil.which("ffprobe")
    pr = subprocess.run([ffprobe, "-v", "error", "-select_streams", "a:0",
                         "-show_entries", "stream=index", "-of", "csv=p=0",
                         str(video)], capture_output=True, text=True)
    return bool(pr.stdout.strip())


def _keyframe_vf(kf: dict, W: int, H: int, dur: float, speed: float,
                 color: list[str] | None = None, reversed_: bool = False) -> str:
    """-vf string for a keyframed block.

    Renders the clip on a transparent WxH canvas: per-frame scale / rotate /
    opacity (geq alpha), then overlays centered plus the x/y offset.
    `t` is segment-local (starts at 0 after setpts).
    Slice 13: the color grade goes into the fg chain right after setpts, so
    the whole graded frame is transformed + composited.
    Slice 14: `reversed_` inserts the `reverse` filter before setpts so the
    trimmed range plays backward.
    """
    SX = _pw_expr(kf.get("scale"), 1.0, "t")
    ROT = _pw_expr(kf.get("rot"), 0.0, "t")
    XX = _pw_expr(kf.get("x"), 0.0, "t")
    YY = _pw_expr(kf.get("y"), 0.0, "t")
    # geq's timestamp variable is T (colorchannelmixer's aa rejects `t`)
    AA = _pw_expr(kf.get("op"), 1.0, "T")
    fg = ",".join([
        *(['reverse'] if reversed_ else []),
        f"setpts=PTS/{speed}",
        *(color or []),
        f"scale=iw*({SX}):ih*({SX}):eval=frame",
        f"rotate=a=({ROT})*PI/180:fillcolor=black@0",
        "format=rgba",
        f"geq=r='r(X,Y)':g='g(X,Y)':b='b(X,Y)':a='p(X,Y)*({AA})'[fg]",
    ])
    bg = f"color=c=black@0:s={W}x{H}:d={dur:.3f}:r=30[bg]"
    ov = (f"[bg][fg]overlay=x=(W-w)/2+({XX}):y=(H-h)/2+({YY})"
          f":eof_action=pass,format=yuv420p")
    return f"{fg};{bg};{ov}"


# ---- Slice 13: color panel (exposure/contrast/saturation/temperature/vignette + LUTs) ----
# block.color = {exposure, contrast, saturation, temperature, vignette} (all optional);
# block.lut = ".cube" filename in backend/luts/. Applied per segment inside the
# block's -vf chain, BEFORE captions/titles burn and BEFORE the keyframe overlay
# (so text stays clean and the grade covers the whole frame).

COLOR_DEFAULTS = {"exposure": 0.0, "contrast": 1.0, "saturation": 1.0,
                  "temperature": 0.0, "vignette": 0.0}

_LUT_NAME_RE = re.compile(r"^[A-Za-z0-9_-]+\.cube$")


def _clean_color(raw) -> dict | None:
    """Sanitize block['color'] -> dict or None (None when everything is default)."""
    if not isinstance(raw, dict):
        return None

    def num(v, lo, hi, d):
        try:
            f = float(v)
        except (TypeError, ValueError):
            return d
        return min(max(f, lo), hi)

    c = {
        "exposure": num(raw.get("exposure"), -1, 1, 0.0),
        "contrast": num(raw.get("contrast"), 0.5, 2, 1.0),
        "saturation": num(raw.get("saturation"), 0, 2, 1.0),
        "temperature": num(raw.get("temperature"), -1, 1, 0.0),
        "vignette": num(raw.get("vignette"), 0, 1, 0.0),
    }
    if all(abs(c[k] - COLOR_DEFAULTS[k]) < 1e-9 for k in c):
        return None
    return c


def _lut_path(name) -> str | None:
    """Validated absolute path of a shipped .cube LUT, or None (also blocks traversal)."""
    if not isinstance(name, str) or not _LUT_NAME_RE.match(name):
        return None
    d = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "luts"))
    p = os.path.abspath(os.path.join(d, name))
    if not p.startswith(d + os.sep) or not os.path.isfile(p):
        return None
    return p


def _color_vf(c: dict | None, lut: str | None) -> list[str]:
    """ffmpeg video filters for one block's color grade.

    Filters at defaults are skipped, so the no-color path stays bit-identical
    to Slice 12. Temperature uses colorbalance (one formula: t<0 flips the
    signs for cool). LUT loads via lut3d after the parametric grade.
    """
    f: list[str] = []
    if c:
        exp, con, sat = c["exposure"], c["contrast"], c["saturation"]
        if abs(exp) > 1e-9 or abs(con - 1.0) > 1e-9 or abs(sat - 1.0) > 1e-9:
            f.append(f"eq=brightness={exp * 0.5:.4f}:contrast={con:.4f}:saturation={sat:.4f}")
        t = c["temperature"]
        if abs(t) > 1e-9:
            f.append(f"colorbalance=rs={0.3 * t:.4f}:gs={0.08 * t:.4f}:bs={-0.35 * t:.4f}")
        v = c["vignette"]
        if v > 1e-9:
            # Measured on ffmpeg's vignette filter: LARGER angle = stronger
            # darkening (angle PI/2 crushes the frame, PI/10 only touches the
            # extreme corners). Map amount 0..1 -> PI/8 (subtle) .. PI/2 (strong).
            angle = math.pi / 8 + v * (math.pi / 2 - math.pi / 8)
            f.append(f"vignette=a={angle:.4f}")
    lut_file = _lut_path(lut)
    if lut_file:
        f.append(f"lut3d=file='{_esc(lut_file)}'")
    return f


# ---- Slice 12: transitions library ----
# block.transition = {"type": <xfade name>, "dur": seconds}, set on the LEFT
# block of a join; applies to the join between that block and the next V1
# block. Absence = hard cut.
TRANSITION_TYPES = (
    "dissolve", "fade", "fadeblack", "fadewhite",
    "wipeleft", "wiperight", "wipeup", "wipedown",
    "slideleft", "slideright", "circleopen", "circleclose",
    "smoothleft", "smoothright",
)

TRANSITION_DUR_MIN, TRANSITION_DUR_MAX = 0.1, 2.0
TRANSITION_DUR_DEFAULT = 0.5


def _clean_transition(raw, dur_a: float, dur_b: float) -> dict | None:
    """Sanitize blocks[i]['transition'] for the join i -> i+1, or None (hard cut)."""
    if not isinstance(raw, dict):
        return None
    typ = raw.get("type")
    if typ not in TRANSITION_TYPES:
        return None
    try:
        dur = float(raw.get("dur", TRANSITION_DUR_DEFAULT))
    except (TypeError, ValueError):
        dur = TRANSITION_DUR_DEFAULT
    dur = min(max(dur, TRANSITION_DUR_MIN), TRANSITION_DUR_MAX)
    # xfade needs offset + dur <= first-input duration; keep the overlap
    # strictly inside both segments.
    dur = min(dur, 0.9 * min(dur_a, dur_b))
    if dur < 0.05:
        return None
    return {"type": typ, "dur": dur}


def _acrossfade_curve_opt(ffmpeg: str) -> str:
    """Option string for a triangular acrossfade curve, per ffmpeg version.

    ffmpeg < 8 uses curve=tri; ffmpeg 8.x renamed it to curve1/curve2
    (default is already tri, but be explicit).
    """
    pr = subprocess.run([ffmpeg, "-hide_banner", "-h", "filter=acrossfade"],
                        capture_output=True, text=True)
    if "curve1" in pr.stdout:
        return "curve1=tri:curve2=tri"
    return "curve=tri"


def _join_segments(ffmpeg: str, pid: str, seg_files: list[str],
                   durs: list[float], joins: list[dict | None]) -> tuple[str, float]:
    """Join per-block segments.

    No transitions anywhere -> the old fast path (concat demuxer, -c copy).
    Otherwise one filter_complex pass: chained xfade (video) + acrossfade
    (audio) for transition joins, concat filters for hard-cut joins.
    Returns (path_used, expected_duration).
    """
    d = project_dir(pid)
    out = d / "edit.mp4"
    if not any(joins):
        lst = d / "edl_list.txt"
        lst.write_text("".join(f"file '{p}'\n" for p in seg_files))
        subprocess.run([ffmpeg, "-y", "-hide_banner", "-loglevel", "error",
                        "-f", "concat", "-safe", "0", "-i", str(lst),
                        "-c", "copy", str(out)], check=True)
        return "copy", sum(durs)

    curve_opt = _acrossfade_curve_opt(ffmpeg)
    fc: list[str] = []
    vcur, acur = "[0:v]", "[0:a]"
    cum = durs[0]  # duration of the chained output after each join
    for i, j in enumerate(joins):
        if j:
            dd = j["dur"]
            off = cum - dd  # xfade offset on the first input's timeline
            fc.append(f"{vcur}[{i + 1}:v]xfade=transition={j['type']}"
                      f":duration={dd:.3f}:offset={off:.3f}[v{i + 1}]")
            fc.append(f"{acur}[{i + 1}:a]acrossfade=d={dd:.3f}:{curve_opt}[a{i + 1}]")
            cum += durs[i + 1] - dd
        else:
            fc.append(f"{vcur}[{i + 1}:v]concat=n=2:v=1:a=0[v{i + 1}]")
            fc.append(f"{acur}[{i + 1}:a]concat=n=2:v=0:a=1[a{i + 1}]")
            cum += durs[i + 1]
        vcur, acur = f"[v{i + 1}]", f"[a{i + 1}]"
    cmd = [ffmpeg, "-y", "-hide_banner", "-loglevel", "error"]
    for s in seg_files:
        cmd += ["-i", s]
    cmd += ["-filter_complex", ";".join(fc), "-map", vcur, "-map", acur,
            "-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
            "-c:a", "aac", str(out)]
    subprocess.run(cmd, check=True)
    return "xfade", cum


# ---- Slice 14: speed ramps, reverse playback, freeze frame ----
# Block fields (all optional):
#   speed_ramps: [{t, speed}] — t in SOURCE timebase (seconds relative to
#     srcStart), ascending. Piecewise-constant: span [t_i, t_{i+1}] plays at
#     speed v_i; the span before the first ramp point uses the block's
#     constant `speed`. No bezier curves — linear-segment stepping only.
#   reversed: bool — play the block's source range backward
#     (trim -> reverse -> setpts=PTS/speed, audio areverse).
#   freeze: {at, dur} — at in source timebase (relative to srcStart); hold
#     that single frame as a still for dur seconds with silent audio, spliced
#     at the output position where source-time `at` plays. Freeze INSERTS
#     time: block output duration grows by dur.
# Documented limitations:
# - Captions are NOT burned on reversed pieces (word order is meaningless
#   backwards); titles still burn.
# - Keyframe transforms (Slice 11) combined with ramps/reverse/freeze apply
#   per sub-segment with piece-local t (edge-case combo; t restarts per piece).
# - Muted pieces in the multi-piece path are still time-scaled before
#   volume=0 so piece durations stay exact (the old single-block path keeps
#   its exact command, muted quirk included).
# - `reverse` buffers the trimmed range in memory — fine for clip lengths
#   here, not for hour-long blocks.


# Single-pass loudnorm (as used in every segment's -af chain) resamples audio
# to a FIXED 96000 Hz output regardless of input rate (verified: 22050,
# 44100, 48000 Hz inputs all -> 96000 Hz). Freeze stills therefore run their
# silence through aresample=96000 so the block-level -c copy concat stays
# uniform. (Muted pieces skip loudnorm and stay at the source rate — the old
# path's quirk, preserved as-is.)
_PIPE_AUDIO_RATE = 96000


def _clean_ramps(raw, span: float, base_speed: float) -> list[tuple[float, float, float]]:
    """Sanitize block['speed_ramps'] -> source-time spans [(b0, b1, speed)].

    Mirrors Timeline.tsx rampSpans() exactly; both must agree on durations.
    """
    pts: list[tuple[float, float]] = []
    if isinstance(raw, list):
        for r in raw:
            if not isinstance(r, dict):
                continue
            try:
                t = min(max(float(r.get("t", 0.0)), 0.0), span)
                v = min(4.0, max(0.25, float(r.get("speed", base_speed))))
            except (TypeError, ValueError):
                continue
            pts.append((t, v))
    pts.sort(key=lambda p: p[0])
    ded: list[tuple[float, float]] = []
    for t, v in pts:
        if ded and abs(ded[-1][0] - t) < 1e-9:
            ded[-1] = (t, v)  # last wins on duplicate times
        else:
            ded.append((t, v))
    bounds = [0.0] + [t for t, _ in ded] + [span]
    uniq: list[float] = []
    for x in bounds:
        if not any(abs(u - x) < 1e-9 for u in uniq):
            uniq.append(x)
    base = min(4.0, max(0.25, base_speed))
    spans = []
    for i in range(len(uniq) - 1):
        b0, b1 = uniq[i], uniq[i + 1]
        if b1 - b0 <= 1e-9:
            continue
        rp = next((v for t, v in ded if abs(t - b0) < 1e-9), None)
        spans.append((b0, b1, rp if rp is not None else base))
    return spans


def _clean_freeze(raw, span: float) -> dict | None:
    """Sanitize block['freeze'] -> {'at', 'dur'} or None."""
    if not isinstance(raw, dict):
        return None
    try:
        at = min(max(float(raw.get("at", 0.0)), 0.0), span)
        dur = max(0.0, float(raw.get("dur", 0.0)))
    except (TypeError, ValueError):
        return None
    if dur <= 1e-9:
        return None
    return {"at": at, "dur": dur}


def _source_audio_params(video) -> tuple[int, str] | None:
    """(sample_rate, channel_layout) of the source's first audio stream, or None."""
    ffprobe = shutil.which("ffprobe")
    pr = subprocess.run([ffprobe, "-v", "error", "-select_streams", "a:0",
                         "-show_entries", "stream=sample_rate,channel_layout,channels",
                         "-of", "default=nw=1", str(video)],
                        capture_output=True, text=True)
    kv = {}
    for line in pr.stdout.splitlines():
        if "=" in line:
            k, v = line.split("=", 1)
            kv[k.strip()] = v.strip()
    try:
        rate = int(kv.get("sample_rate", ""))
    except ValueError:
        return None
    layout = kv.get("channel_layout") or ("mono" if kv.get("channels") == "1" else "stereo")
    return rate, layout


def _plan_pieces(span: float, base_speed: float, ramps, freeze,
                 reversed_: bool) -> list[tuple]:
    """Output-ordered piece plan for a Slice-14 block.

    Each piece is ('seg', s0, s1, speed) with s0/s1 in source-relative
    timebase, or ('still', at, dur, None). Seg spans always tile [0, span];
    the still is spliced where source-time `at` plays (mirrored when
    reversed, since a reversed sequence puts it at the mirrored position).
    """
    spans = ramps if ramps else [(0.0, span, base_speed)]
    if freeze:
        at = freeze["at"]
        split = []
        for b0, b1, v in spans:
            if b0 < at - 1e-9 and at < b1 - 1e-9:
                split += [(b0, at, v), (at, b1, v)]
            else:
                split.append((b0, b1, v))
        pre = [("seg", b0, b1, v) for b0, b1, v in split if b1 <= at + 1e-9]
        post = [("seg", b0, b1, v) for b0, b1, v in split if b0 >= at - 1e-9]
        seq = pre + [("still", at, freeze["dur"], None)] + post
    else:
        seq = [("seg", b0, b1, v) for b0, b1, v in spans]
    if reversed_:
        seq = seq[::-1]
    return seq


def _srt_style() -> str:
    """ASS force_style shared by the old single-block path and Slice-14 pieces."""
    return (f"FontName={_pick_font()},FontSize=20,PrimaryColour=&HFFFFFF,"
            f"OutlineColour=&H90000000,BorderStyle=1,Outline=2,Shadow=0,"
            f"Alignment=2,MarginV=60")


def _render_seg_piece(ffmpeg: str, pid: str, video, has_audio: bool,
                      W: int, H: int, norm_tail: str,
                      s0_abs: float, s1_abs: float, speed: float,
                      muted: bool, reversed_: bool,
                      kf: dict | None, color_vf: list[str],
                      srt_text: str | None, title_fs: list[str],
                      out_path, piece_dur: float, seg_tag: str) -> None:
    """Render one source-span piece of a Slice-14 block.

    Same trim/speed/color/normalize/caption chain as the old path, with
    `reverse` before setpts and `areverse` before atempo when reversed.
    Identical WxH/fps/pix_fmt/codec to every other piece so the block-level
    concat (-c copy) and the join stage keep working.
    """
    vf_pre = ["reverse"] if reversed_ else []
    if kf:
        vf_str = _keyframe_vf(kf, W, H, piece_dur, speed, color_vf, reversed_)
        vf_str += ",fps=30,settb=AVTB"
    else:
        vf_str = ",".join(vf_pre + [f"setpts=PTS/{speed}"] + color_vf + [norm_tail])
    if srt_text and srt_text.strip():
        srt_path = project_dir(pid) / f"{seg_tag}.srt"
        srt_path.write_text(srt_text)
        vf_str += "," + f"subtitles='{_esc(str(srt_path))}':force_style='{_srt_style()}'"
    if title_fs:
        vf_str += "," + ",".join(title_fs)
    af_pre = "areverse," if reversed_ else ""
    af_core = (f"{_atempo(speed)},volume=0" if muted
               else f"{_atempo(speed)},loudnorm=I=-14:TP=-1.0:LRA=11")
    af = af_pre + af_core
    cmd = [ffmpeg, "-y", "-hide_banner", "-loglevel", "error",
           "-ss", str(s0_abs), "-to", str(s1_abs), "-i", str(video)]
    if not has_audio:
        cmd += ["-f", "lavfi", "-i",
                f"anullsrc=r=48000:cl=stereo:d={(s1_abs - s0_abs):.3f}",
                "-map", "0:v:0", "-map", "1:a:0"]
    cmd += ["-vf", vf_str, "-af", af,
            "-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
            "-c:a", "aac", str(out_path)]
    subprocess.run(cmd, check=True)


def _render_still_piece(ffmpeg: str, frame_png, norm_tail: str, dur: float,
                        audio_params: tuple[int, str], title_fs: list[str],
                        out_path) -> None:
    """Render a freeze-frame still: loop the extracted frame, silent audio.

    Silent audio is resampled to _PIPE_AUDIO_RATE with the source's channel
    layout so -c copy concats stay uniform with loudnorm'd seg pieces.
    """
    rate, layout = audio_params
    vf = norm_tail + ("," + ",".join(title_fs) if title_fs else "")
    cmd = [ffmpeg, "-y", "-hide_banner", "-loglevel", "error",
           "-loop", "1", "-framerate", "30", "-t", f"{dur:.3f}",
           "-i", str(frame_png),
           "-f", "lavfi", "-i", f"anullsrc=r={rate}:cl={layout}:d={dur:.3f}",
           "-vf", vf,
           "-af", f"aresample={_PIPE_AUDIO_RATE},aformat=channel_layouts={layout}",
           "-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
           "-c:a", "aac", str(out_path)]
    subprocess.run(cmd, check=True)


def _titles_for_block(titles: list[dict], edit_cursor: float) -> list[dict]:
    """Titles overlapping this block, shifted into the block's local time."""
    out = []
    for tl in titles:
        s = float(tl.get("start", 0)) - edit_cursor
        e = float(tl.get("end", 0)) - edit_cursor
        if e > 0 and s < 1e9:
            out.append({**tl, "start": max(0.0, s), "end": max(0.0, e)})
    return out


def _title_filters(pid: str, titles: list[dict]) -> list[str]:
    """drawtext filters for title overlays (edit timebase)."""
    font = _font_file()
    if not font or not titles:
        return []
    filters = []
    d = project_dir(pid)
    for n, tl in enumerate(titles):
        text = (tl.get("text") or "").strip()
        if not text:
            continue
        start, end = float(tl.get("start", 0)), float(tl.get("end", 3))
        if end <= start:
            continue
        tf = d / f"title_{n}.txt"
        tf.write_text(text)
        size = int(tl.get("size", 48))
        y = "120" if tl.get("position", "bottom") == "top" else "(h-text_h-120)"
        filters.append(
            f"drawtext=fontfile='{_esc(font)}':textfile='{_esc(str(tf))}'"
            f":fontsize={size}:fontcolor=white"
            f":borderw=2:bordercolor=black@0.8"
            f":x=(w-text_w)/2:y={y}"
            f":enable='between(t,{start:.2f},{end:.2f})'")
    return filters


def run(job, report) -> dict:
    params = job.params or {}
    pid = job.project_id
    blocks = params.get("blocks") or []
    captions = params.get("captions", True)
    titles = params.get("titles") or []
    if not blocks:
        raise RuntimeError("empty timeline — nothing to render")

    video = get_video_path(pid)
    if video is None:
        raise RuntimeError("no uploaded video found for project")
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        raise RuntimeError("ffmpeg not found on PATH")

    t = load_json(pid, "transcript.json") or {}
    words = t.get("words", [])

    # Slice 12: all segments must be xfade-compatible — identical WxH,
    # fps, pix_fmt and timebase. Normalize everything to the project canvas.
    proj_wh = _source_wh(video)
    W, H = proj_wh
    has_audio = _source_has_audio(video)
    norm_tail = (f"scale={W}x{H}:force_original_aspect_ratio=decrease,"
                 f"pad={W}:{H}:(ow-iw)/2:(oh-ih)/2,"
                 f"fps=30,format=yuv420p,settb=AVTB")

    seg_files: list[str] = []
    seg_durs: list[float] = []
    kept_blocks: list[dict] = []
    total = len(blocks)
    edit_cursor = 0.0  # position in the final (edit timebase) video
    # Slice 14: freeze stills need silent audio matching the source's params
    # so the block-level -c copy concat stays uniform.
    src_audio = _source_audio_params(video) if has_audio else None
    for n, b in enumerate(blocks):
        src_start = float(b["srcStart"])
        src_end = float(b["srcEnd"])
        speed = min(4.0, max(0.25, float(b.get("speed", 1.0))))
        muted = bool(b.get("muted", False))
        if src_end <= src_start:
            continue
        span = src_end - src_start
        # ---- Slice 14: ramps / reverse / freeze ----
        ramps = _clean_ramps(b.get("speed_ramps"), span, speed)
        freeze = _clean_freeze(b.get("freeze"), span)
        reversed_ = bool(b.get("reversed", False))
        s14 = bool(ramps) or freeze is not None or reversed_
        ramp_spans = ramps if ramps else [(0.0, span, speed)]
        out_dur = (sum((b1 - b0) / v for b0, b1, v in ramp_spans)
                   + (freeze["dur"] if freeze else 0.0))
        kf = _clean_keyframes(b.get("keyframes"), out_dur)
        color_vf = _color_vf(_clean_color(b.get("color")), b.get("lut"))
        out = project_dir(pid) / f"edl_seg_{n}.mp4"

        if s14:
            # ---- Slice 14: multi-piece path. Each piece renders with the
            # same trim/speed/color/normalize chain as the old path, then the
            # pieces are concatenated (-c copy) into the block's segment. ----
            pieces = _plan_pieces(span, speed, ramps, freeze, reversed_)
            piece_files: list[str] = []
            piece_offset = 0.0  # this piece's offset in the block (output timebase)
            frame_png = None
            # Still audio must match the seg pieces: loudnorm'd pieces come out
            # at _PIPE_AUDIO_RATE; muted pieces (no loudnorm) stay at src rate.
            src_rate, src_layout = src_audio or (48000, "stereo")
            still_audio = ((_PIPE_AUDIO_RATE if not muted else src_rate), src_layout)
            if freeze:
                frame_png = project_dir(pid) / f"edl_seg_{n}_freeze.png"
                subprocess.run(
                    [ffmpeg, "-y", "-hide_banner", "-loglevel", "error",
                     "-ss", str(src_start + freeze["at"]), "-i", str(video),
                     "-frames:v", "1", str(frame_png)], check=True)
            for m, p in enumerate(pieces):
                pf = project_dir(pid) / f"edl_seg_{n}_p{m}.mp4"
                if p[0] == "still":
                    _, at, dur, _ = p
                    title_fs = _title_filters(
                        pid, _titles_for_block(titles, edit_cursor + piece_offset))
                    _render_still_piece(ffmpeg, frame_png, norm_tail, dur,
                                        still_audio, title_fs, pf)
                    piece_offset += dur
                else:
                    _, s0, s1, v = p
                    pdur = (s1 - s0) / v
                    srt_text = None
                    if captions and words and not reversed_:
                        srt_text = _build_srt_scaled(
                            words, src_start + s0, src_start + s1, v)
                    title_fs = _title_filters(
                        pid, _titles_for_block(titles, edit_cursor + piece_offset))
                    pkf = (_clean_keyframes(b.get("keyframes"), pdur)
                           if b.get("keyframes") else None)
                    _render_seg_piece(ffmpeg, pid, video, has_audio, W, H, norm_tail,
                                      src_start + s0, src_start + s1, v,
                                      muted, reversed_, pkf, color_vf,
                                      srt_text, title_fs, pf, pdur,
                                      f"edl_seg_{n}_p{m}")
                    piece_offset += pdur
                piece_files.append(str(pf))
            lst = project_dir(pid) / f"edl_seg_{n}_pieces.txt"
            lst.write_text("".join(f"file '{p}'\n" for p in piece_files))
            subprocess.run([ffmpeg, "-y", "-hide_banner", "-loglevel", "error",
                            "-f", "concat", "-safe", "0", "-i", str(lst),
                            "-c", "copy", str(out)], check=True)
            for pf in piece_files:
                try:
                    os.unlink(pf)
                except OSError:
                    pass
            try:
                if frame_png:
                    os.unlink(frame_png)
                lst.unlink()
            except OSError:
                pass
            seg_files.append(str(out))
            seg_durs.append(out_dur)
            kept_blocks.append(b)
            edit_cursor += out_dur
            report(0.1 + 0.8 * (n + 1) / total)
            continue

        srt_path = None
        cap_filters: list[str] = []
        if captions and words:
            srt = _build_srt_scaled(words, src_start, src_end, speed)
            if srt.strip():
                srt_path = project_dir(pid) / f"edl_seg_{n}.srt"
                srt_path.write_text(srt)
                cap_filters.append(f"subtitles='{_esc(str(srt_path))}':force_style='{_srt_style()}'")
        cap_filters += _title_filters(pid, _titles_for_block(titles, edit_cursor))

        if kf:
            # ---- Slice 11: keyframed transform path (captions/titles stay
            # fixed on the canvas, applied after the overlay) ----
            vf_str = _keyframe_vf(kf, W, H, out_dur, speed, color_vf)
            if cap_filters:
                vf_str += "," + ",".join(cap_filters)
            vf_str += ",fps=30,settb=AVTB"  # Slice 12: xfade-safe CFR + timebase
        else:
            # ---- original path + Slice 12 normalization ----
            # Slice 13: color grade sits after setpts and before the
            # geometry/pix_fmt normalization + captions/titles burn.
            vf = [f"setpts=PTS/{speed}"] + color_vf + [norm_tail] + cap_filters
            vf_str = ",".join(vf)

        # Slice 12: every segment carries an audio stream so acrossfade's
        # filter graph is uniform. Muted = silent audio, not dropped stream.
        af = "volume=0" if muted else f"{_atempo(speed)},loudnorm=I=-14:TP=-1.0:LRA=11"
        out = project_dir(pid) / f"edl_seg_{n}.mp4"
        cmd = [ffmpeg, "-y", "-hide_banner", "-loglevel", "error",
               "-ss", str(src_start), "-to", str(src_end), "-i", str(video)]
        if not has_audio:
            # synthesize silence matching the segment's source span; the -af
            # chain (atempo/volume) then shapes it exactly like real audio
            cmd += ["-f", "lavfi", "-i",
                    f"anullsrc=r=48000:cl=stereo:d={(src_end - src_start):.3f}",
                    "-map", "0:v:0", "-map", "1:a:0"]
        cmd += ["-vf", vf_str, "-af", af,
                "-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
                "-c:a", "aac", str(out)]
        subprocess.run(cmd, check=True)
        seg_files.append(str(out))
        seg_durs.append(out_dur)
        kept_blocks.append(b)
        edit_cursor += out_dur  # == (src_end - src_start) / speed on the old path
        report(0.1 + 0.8 * (n + 1) / total)

    if not seg_files:
        raise RuntimeError("all blocks were empty")

    # ---- Slice 12: transitions at joins (transition on left block of join) ----
    joins = [_clean_transition(kept_blocks[i].get("transition"), seg_durs[i], seg_durs[i + 1])
             for i in range(len(kept_blocks) - 1)]
    join_path, expected_dur = _join_segments(ffmpeg, pid, seg_files, seg_durs, joins)
    out = project_dir(pid) / "edit.mp4"
    for p in seg_files:
        try:
            os.unlink(p)
        except OSError:
            pass

    # output duration via ffprobe
    ffprobe = shutil.which("ffprobe")
    pr = subprocess.run([ffprobe, "-v", "error", "-show_entries",
                         "format=duration", "-of", "default=nw=1:nk=1",
                         str(out)], capture_output=True, text=True)
    out_dur = round(float(pr.stdout.strip()), 1)

    edl = {"blocks": blocks, "output_duration": out_dur,
           "captions": captions, "titles": titles,
           "transitions": sum(1 for j in joins if j), "join_path": join_path,
           "ramps": sum(1 for x in blocks if x.get("speed_ramps")),
           "reversed": sum(1 for x in blocks if x.get("reversed")),
           "freezes": sum(1 for x in blocks if x.get("freeze"))}
    save_json(pid, "edit_edl.json", edl)
    report(1.0)
    return {"file": out.name, "blocks": len(blocks),
            "output_duration": out_dur, "titles": len(titles),
            "transitions": edl["transitions"], "join_path": join_path}
