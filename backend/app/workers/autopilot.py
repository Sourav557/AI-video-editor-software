"""Worker: autopilot — the long-video self-editor (Slice 8).

Unlike the shorts pipeline (which hunts for highlights), autopilot cleans the
WHOLE video on autopilot: cut silences, optionally cut filler words, burn
captions, normalize loudness — one finished long video, no overcutting.

Params: remove_silence (default True), silence_pad (default 0.2s),
        remove_fillers (default False), captions (default True).
Output: autopilot.mp4 + autopilot_edl.json (the edit decision list the
timeline renders). Idempotent.
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
import types

from ..projects import (audio_path, get_video_path, load_json, project_dir,
                        save_json)
from .caption import _build_srt, _esc, _pick_font
from .score import FILLERS


def _ensure(pid: str, name: str, mod_name: str, report, frac: float):
    """Run a worker directly if its output JSON is missing (single-threaded
    orchestrator: the agent/autopilot must never queue-and-wait)."""
    import importlib
    mod = importlib.import_module(f"app.workers.{mod_name}")
    job = types.SimpleNamespace(project_id=pid, params={})
    return mod.run(job, lambda p: report(frac * p))


def _complement(silences: list[dict], duration: float, pad: float):
    """Kept ranges = full timeline minus silences (with padding)."""
    cuts = []
    for s in silences:
        a, b = max(0.0, s["start"] - pad), min(duration, s["end"] + pad)
        if b > a:
            cuts.append((a, b))
    cuts.sort()
    kept, cur = [], 0.0
    for a, b in cuts:
        if a > cur:
            kept.append([cur, a])
        cur = max(cur, b)
    if cur < duration:
        kept.append([cur, duration])
    return kept, cuts


def _cut_fillers(kept: list[list[float]], words: list[dict]):
    """Cut filler-word ranges out of kept ranges; merge slivers back."""
    filler_spans = []
    for w in words:
        toks = re.findall(r"[a-z']+", w["word"].lower())
        if any(t in FILLERS for t in toks):
            filler_spans.append((max(0.0, w["start"] - 0.05), w["end"] + 0.08))
    new_kept = []
    removed = []
    for a, b in kept:
        cuts = sorted(s for s in filler_spans if s[1] > a and s[0] < b)
        cur = a
        for fa, fb in cuts:
            fa, fb = max(fa, a), min(fb, b)
            if fa > cur:
                new_kept.append([cur, fa])
            removed.append((fa, fb))
            cur = fb
        if cur < b:
            new_kept.append([cur, b])
    # merge fragments separated by < 0.3s (avoids choppy micro-cuts)
    merged = []
    for a, b in new_kept:
        if merged and a - merged[-1][1] < 0.3:
            merged[-1][1] = b
        else:
            merged.append([a, b])
    # drop fragments shorter than 0.4s by merging into neighbour
    final = []
    for a, b in merged:
        if final and (b - a) < 0.4:
            final[-1][1] = b
        else:
            final.append([a, b])
    return final, removed


def _probe_duration(video) -> float:
    ffprobe = shutil.which("ffprobe")
    p = subprocess.run([ffprobe, "-v", "error", "-show_entries",
                        "format=duration", "-of", "default=nw=1:nk=1",
                        str(video)], capture_output=True, text=True)
    return float(p.stdout.strip())


def _render_segment(pid: str, a: float, b: float, words: list[dict],
                    captions: bool, name: str) -> str:
    video = get_video_path(pid)
    ffmpeg = shutil.which("ffmpeg")
    vf = []
    srt_path = None
    if captions:
        srt_path = project_dir(pid) / f"{name}.srt"
        srt_path.write_text(_build_srt(words, a, b))
        style = (f"FontName={_pick_font()},FontSize=20,PrimaryColour=&HFFFFFF,"
                 f"OutlineColour=&H90000000,BorderStyle=1,Outline=2,Shadow=0,"
                 f"Alignment=2,MarginV=60")
        vf.append(f"subtitles='{_esc(str(srt_path))}':force_style='{style}'")
    out = project_dir(pid) / f"{name}.mp4"
    cmd = [ffmpeg, "-y", "-hide_banner", "-loglevel", "error",
           "-ss", str(a), "-to", str(b), "-i", str(video)]
    if vf:
        cmd += ["-vf", ",".join(vf)]
    cmd += ["-af", "loudnorm=I=-14:TP=-1.0:LRA=11",
            "-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
            "-c:a", "aac", str(out)]
    subprocess.run(cmd, check=True)
    return str(out)


def run(job, report) -> dict:
    params = job.params or {}
    pid = job.project_id
    remove_silence = params.get("remove_silence", True)
    silence_pad = float(params.get("silence_pad", 0.2))
    remove_fillers = params.get("remove_fillers", False)
    captions = params.get("captions", True)

    video = get_video_path(pid)
    if video is None:
        raise RuntimeError("no uploaded video found for project")
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        raise RuntimeError("ffmpeg not found on PATH")

    # 1. make sure analysis exists (direct calls — never queued)
    t = load_json(pid, "transcript.json")
    if t is None:
        _ensure(pid, "transcript.json", "transcribe", report, 0.3)
        t = load_json(pid, "transcript.json")
    s = load_json(pid, "silence.json")
    if s is None:
        _ensure(pid, "silence.json", "silence", report, 0.15)
        s = load_json(pid, "silence.json")
    words = t.get("words", []) if t else []
    duration = _probe_duration(video)
    report(0.45)

    # 2. build the edit decision list
    silences = s.get("silences", []) if (s and remove_silence) else []
    kept, silence_cuts = _complement(silences, duration, silence_pad)
    filler_cuts = []
    if remove_fillers and words:
        kept, filler_cuts = _cut_fillers(kept, words)
    if not kept:
        raise RuntimeError("autopilot would cut everything — "
                           "try a smaller silence pad")
    report(0.55)

    # 3. render kept segments, then concat
    seg_files = []
    for n, (a, b) in enumerate(kept):
        seg_files.append(_render_segment(pid, a, b, words, captions,
                                         f"ap_seg_{n}"))
        report(0.55 + 0.35 * (n + 1) / len(kept))
    lst = project_dir(pid) / "autopilot_list.txt"
    lst.write_text("".join(f"file '{p}'\n" for p in seg_files))
    out = project_dir(pid) / "autopilot.mp4"
    subprocess.run([ffmpeg, "-y", "-hide_banner", "-loglevel", "error",
                    "-f", "concat", "-safe", "0", "-i", str(lst),
                    "-c", "copy", str(out)], check=True)
    for p in seg_files:
        try:
            os.unlink(p)
        except OSError:
            pass

    kept_sec = round(sum(b - a for a, b in kept), 1)
    removed_sec = round(duration - kept_sec, 1)
    edl = {
        "segments": [{"start": round(a, 2), "end": round(b, 2), "kind": "keep"}
                     for a, b in kept],
        "removed": ([{"start": round(a, 2), "end": round(b, 2), "kind": "silence"}
                     for a, b in silence_cuts]
                    + [{"start": round(a, 2), "end": round(b, 2), "kind": "filler"}
                       for a, b in filler_cuts]),
        "source_duration": round(duration, 1),
        "output_duration": kept_sec,
        "cuts": len(silence_cuts) + len(filler_cuts),
        "options": {"remove_silence": remove_silence,
                    "silence_pad": silence_pad,
                    "remove_fillers": remove_fillers, "captions": captions},
    }
    save_json(pid, "autopilot_edl.json", edl)
    report(1.0)
    return {"file": out.name, "kept_seconds": kept_sec,
            "removed_seconds": removed_sec, "cuts": edl["cuts"],
            "segments": len(kept)}
