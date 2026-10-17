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

import os
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


def _keyframe_vf(kf: dict, W: int, H: int, dur: float, speed: float) -> str:
    """-vf string for a keyframed block.

    Renders the clip on a transparent WxH canvas: per-frame scale / rotate /
    opacity (geq alpha), then overlays centered plus the x/y offset.
    `t` is segment-local (starts at 0 after setpts).
    """
    SX = _pw_expr(kf.get("scale"), 1.0, "t")
    ROT = _pw_expr(kf.get("rot"), 0.0, "t")
    XX = _pw_expr(kf.get("x"), 0.0, "t")
    YY = _pw_expr(kf.get("y"), 0.0, "t")
    # geq's timestamp variable is T (colorchannelmixer's aa rejects `t`)
    AA = _pw_expr(kf.get("op"), 1.0, "T")
    fg = ",".join([
        f"setpts=PTS/{speed}",
        f"scale=iw*({SX}):ih*({SX}):eval=frame",
        f"rotate=a=({ROT})*PI/180:fillcolor=black@0",
        "format=rgba",
        f"geq=r='r(X,Y)':g='g(X,Y)':b='b(X,Y)':a='p(X,Y)*({AA})'[fg]",
    ])
    bg = f"color=c=black@0:s={W}x{H}:d={dur:.3f}:r=30[bg]"
    ov = (f"[bg][fg]overlay=x=(W-w)/2+({XX}):y=(H-h)/2+({YY})"
          f":eof_action=pass,format=yuv420p")
    return f"{fg};{bg};{ov}"


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

    seg_files = []
    total = len(blocks)
    edit_cursor = 0.0  # position in the final (edit timebase) video
    src_wh: tuple[int, int] | None = None  # lazy ffprobe, only if keyframes used
    for n, b in enumerate(blocks):
        src_start = float(b["srcStart"])
        src_end = float(b["srcEnd"])
        speed = min(4.0, max(0.25, float(b.get("speed", 1.0))))
        muted = bool(b.get("muted", False))
        if src_end <= src_start:
            continue
        out_dur = (src_end - src_start) / speed
        kf = _clean_keyframes(b.get("keyframes"), out_dur)

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
            if src_wh is None:
                src_wh = _source_wh(video)
            vf_str = _keyframe_vf(kf, src_wh[0], src_wh[1], out_dur, speed)
            if cap_filters:
                vf_str += "," + ",".join(cap_filters)
        else:
            # ---- original path (unchanged) ----
            vf = [f"setpts=PTS/{speed}"] + cap_filters
            vf_str = ",".join(vf)

        af = [f"{_atempo(speed)},loudnorm=I=-14:TP=-1.0:LRA=11"]
        out = project_dir(pid) / f"edl_seg_{n}.mp4"
        cmd = [ffmpeg, "-y", "-hide_banner", "-loglevel", "error",
               "-ss", str(src_start), "-to", str(src_end), "-i", str(video),
               "-vf", vf_str, "-c:v", "libx264", "-preset", "veryfast",
               "-crf", "20"]
        if muted:
            cmd += ["-an"]
        else:
            cmd += ["-af", ",".join(af), "-c:a", "aac"]
        cmd.append(str(out))
        subprocess.run(cmd, check=True)
        seg_files.append(str(out))
        edit_cursor += (src_end - src_start) / speed
        report(0.1 + 0.8 * (n + 1) / total)

    if not seg_files:
        raise RuntimeError("all blocks were empty")

    lst = project_dir(pid) / "edl_list.txt"
    lst.write_text("".join(f"file '{p}'\n" for p in seg_files))
    out = project_dir(pid) / "edit.mp4"
    subprocess.run([ffmpeg, "-y", "-hide_banner", "-loglevel", "error",
                    "-f", "concat", "-safe", "0", "-i", str(lst),
                    "-c", "copy", str(out)], check=True)
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
           "captions": captions, "titles": titles}
    save_json(pid, "edit_edl.json", edl)
    report(1.0)
    return {"file": out.name, "blocks": len(blocks),
            "output_duration": out_dur, "titles": len(titles)}
