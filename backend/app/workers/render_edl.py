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
Slice 15: blocks may carry audio FX — audio_eq (up to 5 parametric EQ
bands), audio_denoise (afftdn), role ('music'/'dialogue'), and ducking
({threshold, ratio}) on music-role blocks (volume-automation dip where the
block's source range overlaps dialogue-marked source ranges).
Slice 16: chroma key (colorkey after geometry normalize), video
stabilization (vidstab two-pass, deshake fallback, hard error when
unavailable), and split screen — V2 overlay tiles composited over the
joined V1 timeline, with per-block canvas layouts and V2 editStart.
Output: edit.mp4 + edit_edl.json. Idempotent.
"""
from __future__ import annotations

import math
import os
import re
import shutil
import subprocess

from ..projects import get_video_path, load_json, project_dir, save_json
from ..project_settings import get_settings
from . import codecs as _codecs
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
                 color: list[str] | None = None, reversed_: bool = False,
                 stab_filter: str | None = None, chroma: dict | None = None,
                 layout: dict | None = None, fps: int = 30) -> str:
    """-vf string for a keyframed block.

    Renders the clip on a transparent WxH canvas: per-frame scale / rotate /
    opacity (geq alpha), then overlays centered plus the x/y offset.
    `t` is segment-local (starts at 0 after setpts).
    Slice 13: the color grade goes into the fg chain right after setpts, so
    the whole graded frame is transformed + composited.
    Slice 14: `reversed_` inserts the `reverse` filter before setpts so the
    trimmed range plays backward.
    Slice 16: `stab_filter` (vidstabdetect for pass 1 / vidstabtransform for
    pass 2 / deshake) stabilizes the raw frame right after setpts; `chroma`
    keys after the grade (colorkey -> yuva420p, composited by the overlay);
    `layout` aspect-fits the fg into the rect and re-centers the overlay on
    the rect instead of the full canvas.
    """
    SX = _pw_expr(kf.get("scale"), 1.0, "t")
    ROT = _pw_expr(kf.get("rot"), 0.0, "t")
    XX = _pw_expr(kf.get("x"), 0.0, "t")
    YY = _pw_expr(kf.get("y"), 0.0, "t")
    # geq's timestamp variable is T (colorchannelmixer's aa rejects `t`)
    AA = _pw_expr(kf.get("op"), 1.0, "T")
    fg_parts: list[str] = []
    if reversed_:
        fg_parts.append("reverse")
    fg_parts.append(f"setpts=PTS/{speed}")
    if stab_filter:
        fg_parts.append(stab_filter)
    fg_parts += (color or [])
    if chroma:
        fg_parts.append(_chroma_vf(chroma))
    if layout:
        lw, lh = layout["w"], layout["h"]
        fg_parts.append(f"scale={lw}:{lh}:force_original_aspect_ratio=decrease")
        ox = f"{layout['x']}+({lw}-w)/2+({XX})"
        oy = f"{layout['y']}+({lh}-h)/2+({YY})"
    else:
        ox = f"(W-w)/2+({XX})"
        oy = f"(H-h)/2+({YY})"
    fg_parts += [
        f"scale=iw*({SX}):ih*({SX}):eval=frame",
        f"rotate=a=({ROT})*PI/180:fillcolor=black@0",
        "format=rgba",
        f"geq=r='r(X,Y)':g='g(X,Y)':b='b(X,Y)':a='p(X,Y)*({AA})'[fg]",
    ]
    fg = ",".join(fg_parts)
    bg = f"color=c=black@0:s={W}x{H}:d={dur:.3f}:r={fps}[bg]"
    ov = (f"[bg][fg]overlay=x={ox}:y={oy}"
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


# ---- Slice 15: audio FX (parametric EQ, denoise, ducking) ----
# Block fields (all optional):
#   audio_eq: [{f, g, w}] — up to 5 parametric bands (ffmpeg `equalizer`,
#     t=q). f: 20–20000 Hz, g: -12..12 dB, w: Q factor 0.5–4.
#   audio_denoise: bool — FFT denoise via `afftdn`. Defaults are NOT used:
#     bare `afftdn` (noise_floor=-50) measured ~0dB reduction on test
#     content; `afftdn=nf=-25` measured -12dB on realistic hiss with the
#     wanted signal untouched (see Slice 15 verification).
#   role: 'music' | 'dialogue' — marks the block's purpose.
#   ducking: {threshold, ratio} — on a music-role block, dips its volume
#     during the SOURCE-time ranges where dialogue-role blocks exist.
# Per block/piece -af chain order:
#   atempo -> equalizer... -> afftdn -> volume(duck expr) -> loudnorm
# EQ/denoise sit BEFORE loudnorm so it measures the processed audio. The
# ducking volume expression ALSO sits before loudnorm: loudnorm's EOF flush
# emits the tail (~3s) as a single frame stamped with a stale pts_time, so
# any t-based expression placed AFTER loudnorm mis-fires on the tail
# (measured: a between(t,2,6) dip never ended). Pre-loudnorm the dip timing
# is sample-exact; loudnorm's single-pass dynamics may soften the depth a
# little (measured -10.6dB for a -12dB setting — still well past the 6dB
# bar). Muted blocks keep the old `volume=0` and skip all FX (pointless on
# silence).
# Design note (ducking = Option B, volume automation): the timeline
# concatenates blocks — nothing ever plays simultaneously — so a true
# sidechain compressor has nothing to key on. Instead the music block is
# dipped where its source range overlaps dialogue-marked source ranges,
# expressed as a volume eval=frame expression over the block's local output
# time `t` (piece-local in the Slice-14 multi-piece path). `threshold` is
# sanitized and stored but has no function in volume-automation mode; it is
# reserved for a future sidechain implementation. Dip depth = 1/ratio.


def _clean_eq(raw) -> list[dict] | None:
    """Sanitize block['audio_eq'] -> [{f, g, w}] (max 5 bands) or None."""
    if not isinstance(raw, list):
        return None
    bands: list[dict] = []
    for e in raw:
        if not isinstance(e, dict) or len(bands) >= 5:
            continue
        try:
            f = min(20000.0, max(20.0, float(e.get("f", 1000.0))))
            g = min(12.0, max(-12.0, float(e.get("g", 0.0))))
            w = min(4.0, max(0.5, float(e.get("w", 1.0))))
        except (TypeError, ValueError):
            continue
        bands.append({"f": f, "g": g, "w": w})
    return bands or None


def _eq_af(bands: list[dict] | None) -> list[str]:
    """ffmpeg `equalizer` filters for sanitized EQ bands."""
    return [f"equalizer=f={b['f']:g}:t=q:w={b['w']:g}:g={b['g']:g}"
            for b in (bands or [])]


def _clean_role(raw) -> str | None:
    return raw if raw in ("music", "dialogue") else None


def _clean_ducking(raw) -> dict | None:
    """Sanitize block['ducking'] -> {threshold, ratio} or None.

    Presence of the dict = enabled; an explicit enabled:false disables.
    """
    if not isinstance(raw, dict):
        return None
    if raw.get("enabled") is False:
        return None
    try:
        threshold = min(0.5, max(0.02, float(raw.get("threshold", 0.03))))
        ratio = min(20.0, max(2.0, float(raw.get("ratio", 4.0))))
    except (TypeError, ValueError):
        return None
    return {"threshold": threshold, "ratio": ratio}


def _merge_ranges(ranges: list[tuple[float, float]]) -> list[tuple[float, float]]:
    """Merge overlapping/adjacent (a, b) ranges, sorted."""
    out: list[tuple[float, float]] = []
    for a, b in sorted(ranges):
        if b - a <= 1e-9:
            continue
        if out and a <= out[-1][1] + 1e-9:
            out[-1] = (out[-1][0], max(out[-1][1], b))
        else:
            out.append((a, b))
    return out


def _duck_af(ranges: list[tuple[float, float]], dip: float) -> list[str]:
    """volume filter dipping to `dip` during local-output-time `ranges`.

    Commas are pre-escaped (\\,) for embedding in the -af option string,
    the same convention as Slice 11's keyframe expressions.
    """
    if not ranges or not (0.0 < dip < 1.0):
        return []
    cond = "+".join(f"between(t\\,{a:.3f}\\,{b:.3f})" for a, b in ranges)
    return [f"volume='if({cond}\\,{_fmt_num(dip)}\\,1)':eval=frame"]


def _piece_duck_ranges(duck_src: list[tuple[float, float]],
                       s0: float, s1: float, v: float,
                       reversed_: bool) -> list[tuple[float, float]]:
    """Map block source-relative duck ranges into one piece's local output time.

    (s0, s1) is the piece's source-relative span at speed v; when reversed,
    source s1 plays at piece-local t=0.
    """
    out: list[tuple[float, float]] = []
    for lo, hi in duck_src:
        a, c = max(lo, s0), min(hi, s1)
        if c - a <= 1e-9:
            continue
        if reversed_:
            out.append(((s1 - c) / v, (s1 - a) / v))
        else:
            out.append(((a - s0) / v, (c - s0) / v))
    return out


# ---- Slice 16: chroma key, stabilization, split screen ----
# Block fields (all optional):
#   chroma: {color, similarity, blend} — color is a 6-digit hex string
#     ("00FF00", default green; a leading '#' is tolerated and stripped);
#     similarity 0.01–0.5 (default 0.15); blend 0–0.2 (default 0.05).
#     Rendered as colorkey=0x{color}:{similarity}:{blend} AFTER the geometry
#     normalize (so it keys the final canvas-size frame) and BEFORE
#     captions/titles. colorkey outputs yuva420p with the keyed RGB left
#     intact under alpha=0, so the V1 path premultiplies the alpha into
#     RGB (keyed region -> black, matching the canvas) before flattening
#     back to yuv420p — a naive format=yuv420p would just drop the alpha
#     and leave the green behind. In the keyframe path the key goes into
#     the fg chain before the canvas overlay, whose alpha compositing
#     preserves the keyed transparency.
#   stabilize: bool — video stabilization. Prefers vidstab (two-pass:
#     vidstabdetect rendered to a null output, then vidstabtransform
#     inserted BEFORE the geometry normalize, i.e. the raw frame is
#     stabilized, then normalized). Falls back to single-pass deshake.
#     Raises a clear error when NEITHER filter exists in this ffmpeg build
#     (never silently skipped). Two-pass doubles render time for the block.
#   track: 'v1' | 'v2' (default 'v1') — v2 blocks are overlay tiles
#     composited OVER the joined V1 timeline in one final pass (so the
#     xfade join stage is untouched).
#   layout: {x, y, w, h} — pixel rect on the project canvas. V1 blocks: the
#     content is aspect-fit into the rect (absence = fullscreen, the old
#     behavior). V2 tiles: scaled EXACTLY to w×h (absence = bottom-right
#     quarter PiP). All values clamped into the canvas.
#   editStart: seconds (V2 only) — edit-time position where the tile
#     appears (default 0); tile duration = its own block duration.
# V2 tiles support trim/speed/color/LUT/chroma/stabilize. NOT applied on V2:
# captions, titles, keyframes, transitions, speed ramps, reverse, freeze.
# V2 audio is DROPPED (the V1 timeline carries the soundtrack).

_CHROMA_HEX_RE = re.compile(r"^[0-9a-fA-F]{6}$")


def _clean_chroma(raw) -> dict | None:
    """Sanitize block['chroma'] -> {color, similarity, blend} or None."""
    if not isinstance(raw, dict):
        return None
    color = raw.get("color", "")
    if isinstance(color, str):
        color = color.strip().lstrip("#")
    if not isinstance(color, str) or not _CHROMA_HEX_RE.match(color):
        return None

    def num(v, lo, hi, d):
        try:
            f = float(v)
        except (TypeError, ValueError):
            return d
        return min(max(f, lo), hi)

    return {"color": color.upper(),
            "similarity": num(raw.get("similarity"), 0.01, 0.5, 0.15),
            "blend": num(raw.get("blend"), 0.0, 0.2, 0.05)}


def _chroma_vf(c: dict) -> str:
    return f"colorkey=0x{c['color']}:{c['similarity']:.4f}:{c['blend']:.4f}"


def _chroma_flat_vf(c: dict) -> list[str]:
    """colorkey for the single-track V1 path: key, premultiply the alpha
    into RGB (keyed region -> black), flatten to yuv420p.

    colorkey leaves the keyed RGB intact under alpha=0, so a naive
    format=yuv420p right after it just drops the alpha plane and leaves
    the green behind (verified: 87.8% of a green-screen test frame stayed
    green). Premultiplying composites the key over black first (verified:
    0.00% green, foreground object fully intact). The expressions contain
    no commas, so no \\, escaping is needed for the -vf chain.
    """
    return [_chroma_vf(c), "format=rgba",
            "geq=r='r(X,Y)*alpha(X,Y)/255'"
            ":g='g(X,Y)*alpha(X,Y)/255'"
            ":b='b(X,Y)*alpha(X,Y)/255'",
            "format=yuv420p"]


def _clean_track(raw) -> str:
    return "v2" if raw == "v2" else "v1"


def _clean_layout(raw, W: int, H: int) -> dict | None:
    """Sanitize block['layout'] -> {x, y, w, h} pixel rect on the WxH canvas.

    Requires w/h keys; values clamped so the rect stays inside the canvas.
    Returns None when absent/invalid (caller applies its own default).
    """
    if not isinstance(raw, dict) or "w" not in raw or "h" not in raw:
        return None
    try:
        w = int(float(raw.get("w", 0)))
        h = int(float(raw.get("h", 0)))
        x = int(float(raw.get("x", 0)))
        y = int(float(raw.get("y", 0)))
    except (TypeError, ValueError):
        return None
    w = min(max(w, 16), W)
    h = min(max(h, 16), H)
    x = min(max(x, 0), W - w)
    y = min(max(y, 0), H - h)
    return {"x": x, "y": y, "w": w, "h": h}


def _default_v2_layout(W: int, H: int) -> dict:
    """Bottom-right quarter PiP (the V2 default when no layout is given)."""
    w, h = max(16, W // 4), max(16, H // 4)
    return {"x": W - w - 24, "y": H - h - 24, "w": w, "h": h}


def _layout_norm(layout: dict | None, W: int, H: int, norm_tail: str,
                fps: int = 30) -> str:
    """Geometry normalize for a V1 block: fullscreen (norm_tail) or aspect-fit
    into the layout rect, centered, then placed at (x, y) on the WxH canvas."""
    if not layout:
        return norm_tail
    x, y, w, h = layout["x"], layout["y"], layout["w"], layout["h"]
    return (f"scale={w}:{h}:force_original_aspect_ratio=decrease,"
            f"pad={w}:{h}:(ow-iw)/2:(oh-ih)/2,"
            f"pad={W}:{H}:{x}:{y},fps={fps},format=yuv420p,settb=AVTB")


def _clean_edit_start(raw) -> float:
    try:
        return max(0.0, float(raw if raw is not None else 0.0))
    except (TypeError, ValueError):
        return 0.0


_stab_cache: dict[str, tuple[bool, bool]] = {}


def _stab_availability(ffmpeg: str) -> tuple[bool, bool]:
    """(has_vidstab, has_deshake) for this ffmpeg binary, checked once."""
    if ffmpeg not in _stab_cache:
        pr = subprocess.run([ffmpeg, "-hide_banner", "-filters"],
                            capture_output=True, text=True)
        out = pr.stdout
        has_vidstab = "vidstabdetect" in out and "vidstabtransform" in out
        has_deshake = re.search(r"(?m)^\s*[A-Z.]{2,3}\s+deshake\s", out) is not None
        _stab_cache[ffmpeg] = (has_vidstab, has_deshake)
    return _stab_cache[ffmpeg]


_STAB_UNAVAILABLE_MSG = (
    "Stabilization was requested but this ffmpeg build has neither the "
    "vidstab filters (vidstabdetect/vidstabtransform) nor deshake. "
    "Install a full ffmpeg build (e.g. with --enable-libvidstab) to use it.")


def _block_stab_mode(want: bool, avail: tuple[bool, bool]) -> str:
    """'' | 'vidstab' | 'deshake'. Raises when wanted but unavailable."""
    if not want:
        return ""
    if avail[0]:
        return "vidstab"
    if avail[1]:
        return "deshake"
    raise RuntimeError(_STAB_UNAVAILABLE_MSG)


def _stab_pass1(ffmpeg: str, video, s0: float, s1: float, vf_str: str) -> None:
    """vidstab pass 1: run the segment's -vf chain (with vidstabdetect at the
    stabilization point) to a null output; the .trf drives pass 2."""
    subprocess.run([ffmpeg, "-y", "-hide_banner", "-loglevel", "error",
                    "-ss", str(s0), "-to", str(s1), "-i", str(video),
                    "-vf", vf_str, "-an", "-f", "null", "-"], check=True)


def _composite_v2(ffmpeg: str, pid: str, v1_path: str,
                  tiles: list[tuple[str, dict, float, float]]) -> str:
    """Composite V2 overlay tiles over the joined V1 timeline (final pass).

    tiles: [(seg_path, layout, edit_start, edit_end)]. Each tile is delayed
    to its editStart via setpts and gated with enable=between(t,S,E), so
    tiles never disturb the V1 join stage. V1 audio is kept; tile audio was
    dropped at tile-render time. Returns the composite output path.
    """
    d = project_dir(pid)
    out = d / "edit_v2.mp4"
    cmd = [ffmpeg, "-y", "-hide_banner", "-loglevel", "error", "-i", v1_path]
    for seg, _, _, _ in tiles:
        cmd += ["-i", seg]
    fc = []
    cur = "[0:v]"
    for i, (_, lay, s, e) in enumerate(tiles):
        fc.append(f"[{i + 1}:v]setpts=PTS-STARTPTS+{s:.3f}/TB[v2_{i}]")
        fc.append(f"{cur}[v2_{i}]overlay=x={lay['x']}:y={lay['y']}"
                  f":enable='between(t,{s:.3f},{e:.3f})'[c{i}]")
        cur = f"[c{i}]"
    cmd += ["-filter_complex", ";".join(fc), "-map", cur, "-map", "0:a",
            "-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
            "-c:a", "aac", str(out)]
    subprocess.run(cmd, check=True)
    return str(out)


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
                      out_path, piece_dur: float, seg_tag: str,
                      fx_af: list[str] | None = None,
                      duck_af: list[str] | None = None,
                      stab_mode: str = "", trf_path: str | None = None,
                      chroma: dict | None = None,
                      layout: dict | None = None,
                      fps: int = 30) -> None:
    """Render one source-span piece of a Slice-14 block.

    Same trim/speed/color/normalize/caption chain as the old path, with
    `reverse` before setpts and `areverse` before atempo when reversed.
    Identical WxH/fps/pix_fmt/codec to every other piece so the block-level
    concat (-c copy) and the join stage keep working.
    Slice 15: `fx_af` (equalizer/afftdn filters) goes between atempo and
    loudnorm; `duck_af` (volume expression, piece-local t) goes after the
    FX but before loudnorm (t-based expressions must precede loudnorm —
    see module docstring).
    Slice 16: `stab_mode` '' | 'vidstab' | 'deshake'; vidstab runs a detect
    pass to a null output first (via `trf_path`), then the transform pass.
    `chroma` keys after the geometry normalize (before captions); `layout`
    aspect-fits the piece into the canvas rect (V1).
    """
    sub_f = None
    if srt_text and srt_text.strip():
        srt_path = project_dir(pid) / f"{seg_tag}.srt"
        srt_path.write_text(srt_text)
        sub_f = f"subtitles='{_esc(str(srt_path))}':force_style='{_srt_style()}'"

    def vf_for(stab_filter: str | None) -> str:
        if kf:
            s = _keyframe_vf(kf, W, H, piece_dur, speed, color_vf, reversed_,
                             stab_filter=stab_filter, chroma=chroma,
                             layout=layout, fps=fps)
            if sub_f:
                s += "," + sub_f
            if title_fs:
                s += "," + ",".join(title_fs)
            return s + f",fps={fps},settb=AVTB"
        parts = ["reverse"] if reversed_ else []
        parts.append(f"setpts=PTS/{speed}")
        if stab_filter:
            parts.append(stab_filter)
        parts += color_vf + [_layout_norm(layout, W, H, norm_tail)]
        if chroma:
            # colorkey -> yuva420p; flatten back so the segment stays
            # concat/xfade-compatible (V2 tiles keep alpha instead).
            parts += _chroma_flat_vf(chroma)
        if sub_f:
            parts.append(sub_f)
        if title_fs:
            parts += title_fs
        return ",".join(parts)

    if stab_mode == "vidstab":
        _stab_pass1(ffmpeg, video, s0_abs, s1_abs,
                    vf_for(f"vidstabdetect=shakiness=5:result={trf_path}"))
        stab_filter = f"vidstabtransform=input={trf_path}:zoom=1:smoothing=10"
    elif stab_mode == "deshake":
        stab_filter = "deshake"
    else:
        stab_filter = None
    vf_str = vf_for(stab_filter)
    af_pre = "areverse," if reversed_ else ""
    # Slice 15: EQ/denoise, then the ducking volume expression, then
    # loudnorm (volume must precede loudnorm — see module docstring).
    af_core = (f"{_atempo(speed)},volume=0" if muted
               else ",".join([_atempo(speed), *(fx_af or []),
                              *(duck_af or []),
                              "loudnorm=I=-14:TP=-1.0:LRA=11"]))
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


def _render_v2_tile(ffmpeg: str, pid: str, video, lay: dict,
                    chroma: dict | None, color_vf: list[str],
                    stab_mode: str, trf_path: str | None,
                    src_start: float, src_end: float, speed: float,
                    out_path, fps: int = 30) -> None:
    """Render one V2 overlay tile: trim/speed/color/stabilize/chroma.

    No captions, titles, keyframes, ramps, reverse or freeze (documented).
    Video-only — the tile's audio is dropped; V1 carries the soundtrack.
    The tile is scaled EXACTLY to the layout rect (may stretch); when
    chroma is set the alpha is kept (qtrle) so the composite overlay can
    punch the keyed transparency through.
    """
    w, h = lay["w"], lay["h"]

    def vf_for(stab_filter: str | None) -> str:
        parts = [f"setpts=PTS/{speed}"]
        if stab_filter:
            parts.append(stab_filter)
        parts += color_vf
        parts.append(f"scale={w}:{h},setsar=1")
        if chroma:
            # keep the keyed alpha for the overlay composite
            parts += [_chroma_vf(chroma), "format=rgba"]
        parts.append(f"fps={fps},settb=AVTB")
        return ",".join(parts)

    if stab_mode == "vidstab":
        _stab_pass1(ffmpeg, video, src_start, src_end,
                    vf_for(f"vidstabdetect=shakiness=5:result={trf_path}"))
        stab_filter = f"vidstabtransform=input={trf_path}:zoom=1:smoothing=10"
    elif stab_mode == "deshake":
        stab_filter = "deshake"
    else:
        stab_filter = None
    vcodec = (["-c:v", "qtrle"] if chroma
              else ["-c:v", "libx264", "-preset", "veryfast", "-crf", "20"])
    cmd = [ffmpeg, "-y", "-hide_banner", "-loglevel", "error",
           "-ss", str(src_start), "-to", str(src_end), "-i", str(video),
           "-vf", vf_for(stab_filter), "-an",
           *vcodec, str(out_path)]
    subprocess.run(cmd, check=True)


def _render_still_piece(ffmpeg: str, frame_png, norm_tail: str, dur: float,
                        audio_params: tuple[int, str], title_fs: list[str],
                        out_path, fps: int = 30) -> None:
    """Render a freeze-frame still: loop the extracted frame, silent audio.

    Silent audio is resampled to _PIPE_AUDIO_RATE with the source's channel
    layout so -c copy concats stay uniform with loudnorm'd seg pieces.
    """
    rate, layout = audio_params
    vf = norm_tail + ("," + ",".join(title_fs) if title_fs else "")
    cmd = [ffmpeg, "-y", "-hide_banner", "-loglevel", "error",
           "-loop", "1", "-framerate", str(fps), "-t", f"{dur:.3f}",
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

    # ---- Slice 15: layout pre-pass. Ducking maps dialogue ranges (source
    # timebase) into each music block's local output time, so the full edit
    # layout must be known before any block renders. The loop below iterates
    # `layout` instead of `blocks`; empty blocks are skipped identically. ----
    layout: list[dict] = []
    _cur = 0.0
    for n, b in enumerate(blocks):
        src_start = float(b["srcStart"])
        src_end = float(b["srcEnd"])
        if src_end <= src_start:
            continue
        span = src_end - src_start
        speed = min(4.0, max(0.25, float(b.get("speed", 1.0))))
        ramps = _clean_ramps(b.get("speed_ramps"), span, speed)
        freeze = _clean_freeze(b.get("freeze"), span)
        reversed_ = bool(b.get("reversed", False))
        ramp_spans = ramps if ramps else [(0.0, span, speed)]
        out_dur = (sum((b1 - b0) / v for b0, b1, v in ramp_spans)
                   + (freeze["dur"] if freeze else 0.0))
        layout.append({"n": n, "b": b, "src_start": src_start,
                       "src_end": src_end, "span": span, "speed": speed,
                       "ramps": ramps, "freeze": freeze,
                       "reversed": reversed_, "out_dur": out_dur,
                       "edit_start": _cur,
                       "track": _clean_track(b.get("track"))})
        _cur += out_dur

    # Slice 16: split the main V1 sequence from V2 overlay tiles. V2 tiles
    # do not participate in the edit layout, joins or transitions.
    v1 = [L for L in layout if L["track"] == "v1"]
    v2 = [L for L in layout if L["track"] == "v2"]
    if not v1:
        raise RuntimeError("no V1 blocks — the main timeline is empty")

    # Slice 16: stabilization filter availability, checked once per job.
    # Fails fast here so a missing filter never burns render time first.
    stab_avail = (_stab_availability(ffmpeg)
                  if any(bool(b.get("stabilize")) for b in blocks)
                  else (False, False))
    if any(bool(b.get("stabilize")) for b in blocks) and not any(stab_avail):
        # Fail fast: never burn render time before discovering the filter
        # is missing, and never silently skip stabilization.
        raise RuntimeError(_STAB_UNAVAILABLE_MSG)

    # Slice 15: dialogue source ranges (absolute source timebase, merged) —
    # the ducking reference. Muted dialogue blocks are silent: excluded.
    # Slice 16: V1 only (V2 tiles carry no audio).
    dialogue_src = _merge_ranges([
        (L["src_start"], L["src_end"]) for L in v1
        if _clean_role(L["b"].get("role")) == "dialogue"
        and not L["b"].get("muted", False)])

    # Slice 12: all segments must be xfade-compatible — identical WxH,
    # fps, pix_fmt and timebase. Normalize everything to the project canvas.
    # Slice 18: project settings (settings.json) override the canvas size;
    # when nothing was saved yet, the source WxH + 30fps are followed,
    # exactly the pre-Slice-18 behavior.
    settings = get_settings(pid)
    if settings:
        W, H, FPS = settings["width"], settings["height"], settings["fps"]
    else:
        W, H = _source_wh(video)
        FPS = 30
    has_audio = _source_has_audio(video)
    norm_tail = (f"scale={W}x{H}:force_original_aspect_ratio=decrease,"
                 f"pad={W}:{H}:(ow-iw)/2:(oh-ih)/2,"
                 f"fps={FPS},format=yuv420p,settb=AVTB")

    seg_files: list[str] = []
    seg_durs: list[float] = []
    kept_blocks: list[dict] = []
    edit_cursor = 0.0  # position in the final (edit timebase) video
    # Slice 14: freeze stills need silent audio matching the source's params
    # so the block-level -c copy concat stays uniform.
    src_audio = _source_audio_params(video) if has_audio else None
    for li, L in enumerate(v1):
        b = L["b"]
        n = L["n"]
        src_start, src_end = L["src_start"], L["src_end"]
        span, speed = L["span"], L["speed"]
        ramps, freeze, reversed_ = L["ramps"], L["freeze"], L["reversed"]
        out_dur = L["out_dur"]
        muted = bool(b.get("muted", False))
        s14 = bool(ramps) or freeze is not None or reversed_
        kf = _clean_keyframes(b.get("keyframes"), out_dur)
        # ---- Slice 16: per-block chroma / stabilization / canvas layout ----
        stab_mode = _block_stab_mode(bool(b.get("stabilize")), stab_avail)
        chroma = _clean_chroma(b.get("chroma"))
        lay = _clean_layout(b.get("layout"), W, H)
        # ---- Slice 15: per-block audio FX ----
        fx_af = _eq_af(_clean_eq(b.get("audio_eq")))
        if b.get("audio_denoise"):
            # nf=-25, not defaults: measured -12dB hiss reduction vs ~0dB
            # with bare afftdn (see module docstring).
            fx_af.append("afftdn=nf=-25")
        duck_cfg = (_clean_ducking(b.get("ducking"))
                    if _clean_role(b.get("role")) == "music" and not muted else None)
        duck_dip = 1.0 / duck_cfg["ratio"] if duck_cfg else 0.0
        # dialogue overlap in this block's source-relative timebase [0, span]
        duck_src: list[tuple[float, float]] = []
        if duck_cfg and dialogue_src:
            for a, c in dialogue_src:
                lo, hi = max(a, src_start) - src_start, min(c, src_end) - src_start
                if hi - lo > 1e-3:
                    duck_src.append((lo, hi))
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
                trf = (project_dir(pid) / f"edl_seg_{n}_p{m}.trf"
                       if stab_mode == "vidstab" else None)
                if p[0] == "still":
                    _, at, dur, _ = p
                    title_fs = _title_filters(
                        pid, _titles_for_block(titles, edit_cursor + piece_offset))
                    _render_still_piece(ffmpeg, frame_png, norm_tail, dur,
                                        still_audio, title_fs, pf, fps=FPS)
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
                    # Slice 15: piece-local duck ranges (s0/s1 are
                    # source-relative; reversed pieces mirror them).
                    p_duck = (_duck_af(_piece_duck_ranges(duck_src, s0, s1, v, reversed_),
                                       duck_dip) if duck_cfg else [])
                    _render_seg_piece(ffmpeg, pid, video, has_audio, W, H, norm_tail,
                                      src_start + s0, src_start + s1, v,
                                      muted, reversed_, pkf, color_vf,
                                      srt_text, title_fs, pf, pdur,
                                      f"edl_seg_{n}_p{m}", fx_af, p_duck,
                                      stab_mode, str(trf) if trf else None,
                                      chroma, lay, fps=FPS)
                    piece_offset += pdur
                    if trf:
                        try:
                            trf.unlink()
                        except OSError:
                            pass
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
            report(0.1 + 0.8 * (li + 1) / max(1, len(v1)))
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
            def vf_for(stab_filter: str | None) -> str:
                s = _keyframe_vf(kf, W, H, out_dur, speed, color_vf,
                                 stab_filter=stab_filter, chroma=chroma,
                                 layout=lay, fps=FPS)
                if cap_filters:
                    s += "," + ",".join(cap_filters)
                return s + f",fps={FPS},settb=AVTB"  # Slice 12: xfade-safe CFR + timebase
        else:
            # ---- original path + Slice 12 normalization ----
            # Slice 13: color grade sits after setpts and before the
            # geometry/pix_fmt normalization + captions/titles burn.
            # Slice 16: stabilization goes before the geometry normalize
            # (raw frame first), chroma key goes after it (canvas-size
            # frame), layout swaps the fullscreen normalize for a rect fit.
            norm = _layout_norm(lay, W, H, norm_tail, fps=FPS)

            def vf_for(stab_filter: str | None) -> str:
                parts = [f"setpts=PTS/{speed}"]
                if stab_filter:
                    parts.append(stab_filter)
                parts += color_vf + [norm]
                if chroma:
                    parts += _chroma_flat_vf(chroma)
                parts += cap_filters
                return ",".join(parts)

        if stab_mode == "vidstab":
            trf = project_dir(pid) / f"edl_seg_{n}.trf"
            _stab_pass1(ffmpeg, video, src_start, src_end,
                        vf_for(f"vidstabdetect=shakiness=5:result={trf}"))
            stab_filter = f"vidstabtransform=input={trf}:zoom=1:smoothing=10"
        elif stab_mode == "deshake":
            stab_filter = "deshake"
        else:
            stab_filter = None
        vf_str = vf_for(stab_filter)

        # Slice 12: every segment carries an audio stream so acrossfade's
        # filter graph is uniform. Muted = silent audio, not dropped stream.
        # Slice 15: EQ/denoise, then ducking volume, then loudnorm (volume
        # must precede loudnorm — its EOF flush breaks t-based expressions).
        if muted:
            af = "volume=0"
        else:
            duck_local = [(lo / speed, hi / speed) for lo, hi in duck_src]
            af = ",".join([_atempo(speed), *fx_af,
                           *_duck_af(duck_local, duck_dip),
                           "loudnorm=I=-14:TP=-1.0:LRA=11"])
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
        if stab_mode == "vidstab":
            try:
                (project_dir(pid) / f"edl_seg_{n}.trf").unlink()
            except OSError:
                pass
        seg_files.append(str(out))
        seg_durs.append(out_dur)
        kept_blocks.append(b)
        edit_cursor += out_dur  # == (src_end - src_start) / speed on the old path
        report(0.1 + 0.8 * (li + 1) / max(1, len(v1)))

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

    # ---- Slice 16: V2 overlay tiles, composited over the joined V1 timeline.
    # The join stage above is untouched; this is one final re-encode pass.
    # V2 tiles: constant speed only (ramps/reverse/freeze/keyframes not
    # applied); no captions/titles/transitions; audio dropped.
    tiles: list[tuple[str, dict, float, float]] = []
    for L in v2:
        b = L["b"]
        n = L["n"]
        src_start, src_end = L["src_start"], L["src_end"]
        span = L["span"]
        speed = min(4.0, max(0.25, float(b.get("speed", 1.0))))
        vdur = span / speed
        if vdur < 0.05:
            continue
        lay = _clean_layout(b.get("layout"), W, H) or _default_v2_layout(W, H)
        estart = _clean_edit_start(b.get("editStart"))
        chroma = _clean_chroma(b.get("chroma"))
        color_vf = _color_vf(_clean_color(b.get("color")), b.get("lut"))
        stab_mode = _block_stab_mode(bool(b.get("stabilize")), stab_avail)
        tile = project_dir(pid) / f"edl_v2_{n}.mov"
        trf = project_dir(pid) / f"edl_v2_{n}.trf"
        _render_v2_tile(ffmpeg, pid, video, lay, chroma, color_vf, stab_mode,
                        str(trf) if stab_mode == "vidstab" else None,
                        src_start, src_end, speed, tile, fps=FPS)
        try:
            trf.unlink()
        except OSError:
            pass
        tiles.append((str(tile), lay, estart, estart + vdur))
        report(0.9 + 0.05 * (len(tiles)) / max(1, len(v2)))
    if tiles:
        comp = _composite_v2(ffmpeg, pid, str(out), tiles)
        os.replace(comp, str(out))
        for seg, _, _, _ in tiles:
            try:
                os.unlink(seg)
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
           "freezes": sum(1 for x in blocks if x.get("freeze")),
           "eq": sum(1 for x in blocks if x.get("audio_eq")),
           "denoise": sum(1 for x in blocks if x.get("audio_denoise")),
           "ducking": sum(1 for x in blocks
                           if x.get("role") == "music" and x.get("ducking")),
           "chroma": sum(1 for x in blocks if x.get("chroma")),
           "stabilized": sum(1 for x in blocks if x.get("stabilize")),
           "v2_tiles": len(tiles),
           "layouts": sum(1 for x in blocks if x.get("layout"))}
    save_json(pid, "edit_edl.json", edl)

    # ---- Slice 18: codec transcode for the final downloadable file ----
    # No codec option -> the default path is EXACTLY as before (edit.mp4).
    # With a codec option, the EDL render above becomes the mezzanine and
    # the final file is transcoded to edit_<codec>.<ext>.
    export_spec = _codecs.spec_from_params(params)
    if export_spec is not None:
        report(0.95)
        name = _unique_export_name(pid, export_spec["file"])
        _codecs.transcode(ffmpeg, out, project_dir(pid) / name, export_spec)
        report(1.0)
        return {"file": name, "codec": export_spec["codec"],
                "crf": export_spec["crf"], "preset": export_spec["preset"],
                "profile": export_spec["profile"],
                "blocks": len(blocks), "output_duration": out_dur,
                "titles": len(titles), "transitions": edl["transitions"],
                "join_path": join_path}

    report(1.0)
    return {"file": out.name, "blocks": len(blocks),
            "output_duration": out_dur, "titles": len(titles),
            "transitions": edl["transitions"], "join_path": join_path}


def _unique_export_name(pid: str, base: str) -> str:
    """edit_hevc.mp4, or edit_hevc_2.mp4 when it already exists."""
    d = project_dir(pid)
    if not (d / base).exists():
        return base
    stem, ext = base.rsplit(".", 1)
    i = 2
    while (d / f"{stem}_{i}.{ext}").exists():
        i += 1
    return f"{stem}_{i}.{ext}"
