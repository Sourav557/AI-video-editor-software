"""Worker: render_edl — render the user's timeline edit (Slice 9).

Takes an explicit block list (the Filmora-style timeline state):
  blocks: [{id, srcStart, srcEnd, speed, muted}]
Renders each block (trim + speed + optional mute + caption burn with
speed-scaled timestamps), concatenates, normalizes loudness.
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


def run(job, report) -> dict:
    params = job.params or {}
    pid = job.project_id
    blocks = params.get("blocks") or []
    captions = params.get("captions", True)
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
    for n, b in enumerate(blocks):
        src_start = float(b["srcStart"])
        src_end = float(b["srcEnd"])
        speed = min(4.0, max(0.25, float(b.get("speed", 1.0))))
        muted = bool(b.get("muted", False))
        if src_end <= src_start:
            continue

        vf = [f"setpts=PTS/{speed}"]
        srt_path = None
        if captions and words:
            srt = _build_srt_scaled(words, src_start, src_end, speed)
            if srt.strip():
                srt_path = project_dir(pid) / f"edl_seg_{n}.srt"
                srt_path.write_text(srt)
                style = (f"FontName={_pick_font()},FontSize=20,PrimaryColour=&HFFFFFF,"
                         f"OutlineColour=&H90000000,BorderStyle=1,Outline=2,Shadow=0,"
                         f"Alignment=2,MarginV=60")
                vf.append(f"subtitles='{_esc(str(srt_path))}':force_style='{style}'")

        af = [f"{_atempo(speed)},loudnorm=I=-14:TP=-1.0:LRA=11"]
        out = project_dir(pid) / f"edl_seg_{n}.mp4"
        cmd = [ffmpeg, "-y", "-hide_banner", "-loglevel", "error",
               "-ss", str(src_start), "-to", str(src_end), "-i", str(video),
               "-vf", ",".join(vf), "-c:v", "libx264", "-preset", "veryfast",
               "-crf", "20"]
        if muted:
            cmd += ["-an"]
        else:
            cmd += ["-af", ",".join(af), "-c:a", "aac"]
        cmd.append(str(out))
        subprocess.run(cmd, check=True)
        seg_files.append(str(out))
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
           "captions": captions}
    save_json(pid, "edit_edl.json", edl)
    report(1.0)
    return {"file": out.name, "blocks": len(blocks),
            "output_duration": out_dur}
