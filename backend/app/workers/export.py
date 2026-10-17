"""Worker: multi-platform export (Slice 3).

Re-cuts a scored clip (or any start/end range) for a platform preset:
aspect-correct center crop, platform resolution, burned-in captions,
and loudness normalization to the platform target. Fully local (ffmpeg).
Idempotent per (clip_index, platform).
"""
from __future__ import annotations

import json
import shutil
import subprocess

from ..platforms import crop_box, get_preset
from ..projects import get_video_path, load_json, project_dir
from .caption import _build_srt, _esc, _pick_font


def _probe_dims(video) -> tuple[int, int]:
    ffprobe = shutil.which("ffprobe")
    if not ffprobe:
        raise RuntimeError("ffprobe not found on PATH")
    p = subprocess.run(
        [ffprobe, "-v", "error", "-select_streams", "v:0",
         "-show_entries", "stream=width,height", "-of", "json", str(video)],
        capture_output=True, text=True, check=True,
    )
    s = json.loads(p.stdout)["streams"][0]
    return int(s["width"]), int(s["height"])


def run(job, report) -> dict:
    params = job.params or {}
    platform = params.get("platform", "tiktok")
    preset = get_preset(platform)

    clips = load_json(job.project_id, "clips.json")
    if params.get("clip_index") is not None:
        idx = params["clip_index"]
        if not clips or idx >= len(clips["clips"]):
            raise RuntimeError("clip not found — run Find clips first")
        clip = clips["clips"][idx]
        start, end = clip["start"], clip["end"]
        tag = f"clip{idx}"
    else:
        start, end = float(params["start"]), float(params["end"])
        tag = "custom"

    transcript = load_json(job.project_id, "transcript.json") or {}
    video = get_video_path(job.project_id)
    if video is None:
        raise RuntimeError("no uploaded video found")
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        raise RuntimeError("ffmpeg not found on PATH")

    report(0.1)
    sw, sh = _probe_dims(video)
    x, y, cw, ch = crop_box(sw, sh, preset["aspect"])
    W, H = preset["width"], preset["height"]

    srt_path = project_dir(job.project_id) / f"export_{platform}_{tag}.srt"
    srt_path.write_text(_build_srt(transcript.get("words", []), start, end))
    report(0.25)

    out = project_dir(job.project_id) / f"export_{platform}_{tag}.mp4"
    style = (f"FontName={_pick_font()},FontSize=22,PrimaryColour=&HFFFFFF,"
             f"OutlineColour=&H90000000,BorderStyle=1,Outline=2,Shadow=0,"
             f"Alignment=2,MarginV=140")
    vf = (f"crop={cw}:{ch}:{x}:{y},scale={W}:{H},"
          f"subtitles='{_esc(str(srt_path))}':force_style='{style}'")
    af = (f"loudnorm=I={preset['loudness_lufs']}:TP=-1.0:LRA=11")
    cmd = [ffmpeg, "-y", "-hide_banner", "-loglevel", "error",
           "-ss", str(start), "-to", str(end),
           "-i", str(video), "-vf", vf, "-af", af,
           "-c:v", "libx264", "-preset", "veryfast", "-b:v", preset["video_bitrate"],
           "-c:a", "aac", str(out)]
    report(0.4)
    subprocess.run(cmd, check=True)
    report(1.0)
    return {"file": out.name, "platform": platform,
            "resolution": f"{W}x{H}", "clip_index": params.get("clip_index")}
