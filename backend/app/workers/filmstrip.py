"""Worker: filmstrip — timeline thumbnails, Filmora-style (Slice 10).

Extracts one 160x90 JPEG every 5 seconds of source video into
filmstrip/thumb_NNN.jpg + filmstrip.json. The timeline renders these inside
clip blocks, exactly like Filmora's filmstrip view. Idempotent.
"""
from __future__ import annotations

import shutil
import subprocess

from ..projects import get_video_path, project_dir, save_json

INTERVAL = 5.0  # seconds between thumbnails
W, H = 160, 90


def run(job, report) -> dict:
    video = get_video_path(job.project_id)
    if video is None:
        raise RuntimeError("no uploaded video found for project")
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        raise RuntimeError("ffmpeg not found on PATH")

    out_dir = project_dir(job.project_id) / "filmstrip"
    out_dir.mkdir(exist_ok=True)
    for p in out_dir.glob("thumb_*.jpg"):
        p.unlink()
    report(0.2)

    subprocess.run(
        [ffmpeg, "-y", "-hide_banner", "-loglevel", "error",
         "-i", str(video), "-vf", f"fps=1/{INTERVAL},scale={W}:{H}",
         str(out_dir / "thumb_%03d.jpg")],
        check=True)
    report(0.9)

    files = sorted(p.name for p in out_dir.glob("thumb_*.jpg"))
    data = {"interval": INTERVAL, "thumbs": files,
            "width": W, "height": H}
    save_json(job.project_id, "filmstrip.json", data)
    report(1.0)
    return {"thumbs": len(files)}
