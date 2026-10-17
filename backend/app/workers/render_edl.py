"""Worker: render_edl — render the user's timeline edit (Slice 9, keyframes in Slice 11).

Takes an explicit block list (the Filmora-style timeline state):
  blocks: [{id, srcStart, srcEnd, speed, muted, keyframes?}]
Renders each block (trim + speed + optional mute + caption burn with
speed-scaled timestamps), concatenates, normalizes loudness.
Blocks with keyframes render on a transparent canvas with per-frame
scale / rotation / x-y offset / opacity, then overlay centered.
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
                 color: list[str] | None = None) -> str:
    """-vf string for a keyframed block.

    Renders the clip on a transparent WxH canvas: per-frame scale / rotate /
    opacity (geq alpha), then overlays centered plus the x/y offset.
    `t` is segment-local (starts at 0 after setpts).
    Slice 13: the color grade goes into the fg chain right after setpts, so
    the whole graded frame is transformed + composited.
    """
    SX = _pw_expr(kf.get("scale"), 1.0, "t")
    ROT = _pw_expr(kf.get("rot"), 0.0, "t")
    XX = _pw_expr(kf.get("x"), 0.0, "t")
    YY = _pw_expr(kf.get("y"), 0.0, "t")
    # geq's timestamp variable is T (colorchannelmixer's aa rejects `t`)
    AA = _pw_expr(kf.get("op"), 1.0, "T")
    fg = ",".join([
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
    """Titles overlapping this block, shifted into the block's local time."""
    out = []
    for tl in titles:
        s = float(tl.get("start", 0)) - edit_cursor
        e = float(tl.get("end", 0)) - edit_cursor
        if e > 0 and s < 1e9:
            out.append({**tl, "start": max(0.0, s), "end": max(0.0, e)})
    return out


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
    for n, b in enumerate(blocks):
        src_start = float(b["srcStart"])
        src_end = float(b["srcEnd"])
        speed = min(4.0, max(0.25, float(b.get("speed", 1.0))))
        muted = bool(b.get("muted", False))
        if src_end <= src_start:
            continue
        out_dur = (src_end - src_start) / speed
        kf = _clean_keyframes(b.get("keyframes"), out_dur)
        color_vf = _color_vf(_clean_color(b.get("color")), b.get("lut"))

        srt_path = None
        cap_filters: list[str] = []
        if captions and words:
            srt = _build_srt_scaled(words, src_start, src_end, speed)
            if srt.strip():
                srt_path = project_dir(pid) / f"edl_seg_{n}.srt"
                srt_path.write_text(srt)
                style = (f"FontName={_pick_font()},FontSize=20,PrimaryColour=&HFFFFFF,"
                         f"OutlineColour=&H90000000,BorderStyle=1,Outline=2,Shadow=0,"
                         f"Alignment=2,MarginV=60")
                cap_filters.append(f"subtitles='{_esc(str(srt_path))}':force_style='{style}'")
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
        edit_cursor += (src_end - src_start) / speed
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
           "transitions": sum(1 for j in joins if j), "join_path": join_path}
    save_json(pid, "edit_edl.json", edl)
    report(1.0)
    return {"file": out.name, "blocks": len(blocks),
            "output_duration": out_dur, "titles": len(titles),
            "transitions": edl["transitions"], "join_path": join_path}
