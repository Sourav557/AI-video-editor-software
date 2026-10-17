"""Worker: render a vertical (9:16) clip with burned-in captions (ffmpeg, local).

Takes a scored clip, re-cuts it from the source, center-crops to 9:16, and burns
segment captions in a bold bottom style. Idempotent per clip index.
Slice 2: center crop (face-tracked reframing arrives in Slice 3).
"""
from __future__ import annotations

import shutil
import subprocess

from ..projects import get_video_path, load_json, project_dir

WIDTH, HEIGHT = 1080, 1920
FONT_CANDIDATES = ("DejaVu Sans", "Arial", "Liberation Sans", "sans-serif")


def _pick_font() -> str:
    fc_list = shutil.which("fc-list")
    if fc_list:
        out = subprocess.run([fc_list, "--format=%{family}\n"],
                             capture_output=True, text=True).stdout.lower()
        for name in FONT_CANDIDATES:
            if name.lower() in out:
                return name
    return FONT_CANDIDATES[0]


def _srt_time(sec: float) -> str:
    ms = int(round(sec * 1000))
    h, rem = divmod(ms, 3_600_000)
    m, rem = divmod(rem, 60_000)
    s, ms = divmod(rem, 1000)
    return f"{h:02}:{m:02}:{s:02},{ms:03}"


def _build_srt(words: list[dict], start: float, end: float) -> str:
    """Chunk words into readable caption lines, timestamps relative to clip start."""
    in_range = [w for w in words if w["end"] > start and w["start"] < end]
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
        out.append(f"{i}\n{_srt_time(max(0, s - start))} --> {_srt_time(e - start)}\n{t}\n")
    return "\n".join(out)


def _esc(path: str) -> str:
    return path.replace("\\", "\\\\").replace("'", "\\'").replace(":", "\\:")


def run(job, report) -> dict:
    idx = (job.params or {}).get("clip_index", 0)
    clips = load_json(job.project_id, "clips.json")
    if not clips or idx >= len(clips["clips"]):
        raise RuntimeError("clip not found — run Find clips first")
    clip = clips["clips"][idx]

    transcript = load_json(job.project_id, "transcript.json") or {}
    video = get_video_path(job.project_id)
    if video is None:
        raise RuntimeError("no uploaded video found")
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        raise RuntimeError("ffmpeg not found on PATH")

    report(0.1)
    srt_path = project_dir(job.project_id) / f"clip_{idx}.srt"
    srt_path.write_text(_build_srt(transcript.get("words", []),
                                  clip["start"], clip["end"]))
    report(0.25)

    out = project_dir(job.project_id) / f"clip_{idx}.mp4"
    style = (f"FontName={_pick_font()},FontSize=22,PrimaryColour=&HFFFFFF,"
             f"OutlineColour=&H90000000,BorderStyle=1,Outline=2,Shadow=0,"
             f"Alignment=2,MarginV=140")
    vf = (f"crop=ih*9/16:ih,scale={WIDTH}:{HEIGHT},"
          f"subtitles='{_esc(str(srt_path))}':force_style='{style}'")
    cmd = [ffmpeg, "-y", "-hide_banner", "-loglevel", "error",
           "-ss", str(clip["start"]), "-to", str(clip["end"]),
           "-i", str(video), "-vf", vf,
           "-c:v", "libx264", "-preset", "veryfast", "-crf", "23",
           "-c:a", "aac", str(out)]
    report(0.4)
    subprocess.run(cmd, check=True)
    report(1.0)
    return {"file": out.name, "clip_index": idx,
            "duration": clip["duration"], "score": clip["score"]}
