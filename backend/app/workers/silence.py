"""Worker: silence detection via ffmpeg silencedetect (fully local, CPU).

Independent of transcription — the orchestrator runs both without either
blocking the other. Idempotent: re-running overwrites silence.json.
"""
from __future__ import annotations

import re
import shutil
import subprocess

from ..config import SILENCE_MIN_DURATION, SILENCE_NOISE_DB
from ..projects import get_video_path, save_json


def run(job, report) -> dict:
    video = get_video_path(job.project_id)
    if video is None:
        raise RuntimeError("no uploaded video found for project")
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        raise RuntimeError("ffmpeg not found on PATH.")

    report(0.1)
    cmd = [ffmpeg, "-hide_banner", "-i", str(video), "-af",
           f"silencedetect=noise={SILENCE_NOISE_DB}dB:d={SILENCE_MIN_DURATION}",
           "-f", "null", "-"]
    p = subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True)
    report(0.7)

    starts = re.findall(r"silence_start: ([\d.]+)", p.stderr)
    ends = re.findall(r"silence_end: ([\d.]+)", p.stderr)
    silences = [
        {"start": round(float(s), 2), "end": round(float(e), 2),
         "duration": round(float(e) - float(s), 2)}
        for s, e in zip(starts, ends)
    ]
    total_silence = round(sum(s["duration"] for s in silences), 2)
    result = {"silences": silences, "count": len(silences),
              "total_silence_sec": total_silence}
    save_json(job.project_id, "silence.json", result)
    report(1.0)
    return result
