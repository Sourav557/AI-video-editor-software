"""Worker: speech-to-text with word timestamps (faster-whisper, fully local).

Idempotent: re-running overwrites transcript.json with the same content.
"""
from __future__ import annotations

import shutil
import subprocess

from ..config import WHISPER_DEVICE, WHISPER_MODEL
from ..projects import audio_path, get_video_path, save_json

_model = None


def _ffmpeg() -> str:
    exe = shutil.which("ffmpeg")
    if not exe:
        raise RuntimeError(
            "ffmpeg not found on PATH. Install it (https://ffmpeg.org/download.html) "
            "and restart the backend."
        )
    return exe


def _get_model():
    global _model
    if _model is None:
        from faster_whisper import WhisperModel

        if WHISPER_DEVICE == "cuda":
            device = "cuda"
        elif WHISPER_DEVICE == "cpu":
            device = "cpu"
        else:
            try:
                import ctranslate2
                device = "cuda" if ctranslate2.get_cuda_device_count() > 0 else "cpu"
            except Exception:
                device = "cpu"
        compute = "float16" if device == "cuda" else "int8"
        _model = WhisperModel(WHISPER_MODEL, device=device, compute_type=compute)
    return _model


def _extract_audio(video, wav_out) -> None:
    subprocess.run(
        [_ffmpeg(), "-y", "-hide_banner", "-loglevel", "error",
         "-i", str(video), "-vn", "-ac", "1", "-ar", "16000", str(wav_out)],
        check=True,
    )


def run(job, report) -> dict:
    video = get_video_path(job.project_id)
    if video is None:
        raise RuntimeError("no uploaded video found for project")

    report(0.05)
    wav = audio_path(job.project_id)
    if not wav.exists():  # cached across re-runs
        _extract_audio(video, wav)
    report(0.15)

    model = _get_model()
    segments, info = model.transcribe(str(wav), word_timestamps=True)

    out_segments, words = [], []
    seg_list = list(segments)
    total = max(1, len(seg_list))
    for i, s in enumerate(seg_list):
        out_segments.append({"start": round(s.start, 2), "end": round(s.end, 2),
                             "text": s.text.strip()})
        for w in (s.words or []):
            words.append({"start": round(w.start, 2), "end": round(w.end, 2),
                          "word": w.word})
        report(0.15 + 0.8 * (i + 1) / total)

    result = {
        "language": info.language,
        "language_probability": round(info.language_probability, 3),
        "model": WHISPER_MODEL,
        "segments": out_segments,
        "words": words,
        "word_count": len(words),
    }
    save_json(job.project_id, "transcript.json", result)
    report(1.0)
    return result
