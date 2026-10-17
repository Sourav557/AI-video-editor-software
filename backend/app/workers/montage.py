"""Worker: montage — stitch scored clips into one highlight reel (Slice 6).

Each clip is rendered as a captioned platform segment (same pipeline as the
export worker), then joined with hard cuts via the ffmpeg concat demuxer
(reliable; crossfade transitions are a future upgrade). Idempotent.
"""
from __future__ import annotations

import os
import shutil
import subprocess

from ..platforms import crop_box, get_preset
from ..projects import get_video_path, load_json, project_dir
from .caption import _build_srt, _esc, _pick_font
from .export import _probe_dims


def _segment(project_id: str, clip: dict, preset: dict, transcript: dict,
             name: str) -> str:
    video = get_video_path(project_id)
    ffmpeg = shutil.which("ffmpeg")
    sw, sh = _probe_dims(video)
    x, y, cw, ch = crop_box(sw, sh, preset["aspect"])
    W, H = preset["width"], preset["height"]

    srt_path = project_dir(project_id) / f"{name}.srt"
    srt_path.write_text(_build_srt(transcript.get("words", []),
                                  clip["start"], clip["end"]))
    style = (f"FontName={_pick_font()},FontSize=22,PrimaryColour=&HFFFFFF,"
             f"OutlineColour=&H90000000,BorderStyle=1,Outline=2,Shadow=0,"
             f"Alignment=2,MarginV=140")
    vf = (f"crop={cw}:{ch}:{x}:{y},scale={W}:{H},"
          f"subtitles='{_esc(str(srt_path))}':force_style='{style}'")
    out = project_dir(project_id) / f"{name}.mp4"
    cmd = [ffmpeg, "-y", "-hide_banner", "-loglevel", "error",
           "-ss", str(clip["start"]), "-to", str(clip["end"]),
           "-i", str(video), "-vf", vf,
           "-af", f"loudnorm=I={preset['loudness_lufs']}:TP=-1.0:LRA=11",
           "-c:v", "libx264", "-preset", "veryfast", "-b:v", preset["video_bitrate"],
           "-c:a", "aac", str(out)]
    subprocess.run(cmd, check=True)
    return str(out)


def run(job, report) -> dict:
    params = job.params or {}
    platform = params.get("platform", "tiktok")
    preset = get_preset(platform)

    clips_data = load_json(job.project_id, "clips.json")
    if not clips_data or not clips_data.get("clips"):
        raise RuntimeError("no clips found — run Find clips first")
    all_clips = clips_data["clips"]
    indices = params.get("clip_indices")
    if not indices:
        indices = [c["index"] for c in all_clips[:3]]
    clips = [all_clips[i] for i in indices if i < len(all_clips)]
    if not clips:
        raise RuntimeError("clip indices out of range")

    transcript = load_json(job.project_id, "transcript.json") or {}
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        raise RuntimeError("ffmpeg not found on PATH")

    seg_files = []
    for n, clip in enumerate(clips):
        seg_files.append(_segment(job.project_id, clip, preset, transcript,
                                  f"montage_seg_{n}"))
        report(0.1 + 0.75 * (n + 1) / len(clips))

    lst = project_dir(job.project_id) / "montage_list.txt"
    lst.write_text("".join(f"file '{p}'\n" for p in seg_files))
    out = project_dir(job.project_id) / f"montage_{platform}.mp4"
    subprocess.run([ffmpeg, "-y", "-hide_banner", "-loglevel", "error",
                    "-f", "concat", "-safe", "0", "-i", str(lst),
                    "-c", "copy", str(out)], check=True)
    # cleanup intermediates (keep the reel)
    for p in seg_files:
        try:
            os.unlink(p)
        except OSError:
            pass

    total = round(sum(c["end"] - c["start"] for c in clips), 1)
    report(1.0)
    return {"file": out.name, "clips": indices, "platform": platform,
            "duration": total, "resolution": f"{preset['width']}x{preset['height']}"}
