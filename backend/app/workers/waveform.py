"""Worker: waveform peaks for the editor timeline (Slice 8).

Reads the mono 16k WAV the transcribe worker extracts, computes ~1500 peak
buckets, and saves waveform.json. Tiny, fast, CPU-only. Idempotent.
"""
from __future__ import annotations

import wave

from ..projects import audio_path, save_json

N_BUCKETS = 1500


def run(job, report) -> dict:
    wav = audio_path(job.project_id)
    if not wav.exists():
        raise RuntimeError("no audio yet — run Analyze first")
    with wave.open(str(wav), "rb") as w:
        n, ch, sw, sr = (w.getnframes(), w.getnchannels(),
                         w.getsampwidth(), w.getframerate())
        raw = w.readframes(n)
    report(0.3)

    import numpy as np
    dtype = {1: np.int8, 2: np.int16, 4: np.int32}[sw]
    a = np.frombuffer(raw, dtype=dtype).astype(np.float32)
    if ch > 1:
        a = a.reshape(-1, ch).mean(axis=1)
    peak = np.abs(a).max()
    if peak > 0:
        a /= peak
    buckets = np.array_split(np.abs(a), N_BUCKETS)
    peaks = [round(float(b.max()) if len(b) else 0.0, 3) for b in buckets]
    report(0.9)

    data = {"peaks": peaks, "duration": round(n / sr, 2), "buckets": N_BUCKETS}
    save_json(job.project_id, "waveform.json", data)
    report(1.0)
    return {"buckets": N_BUCKETS, "duration": data["duration"]}
