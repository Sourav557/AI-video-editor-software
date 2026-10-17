"""Worker: Qwen3-TTS voiceover generation (Slice 4). Fully local, Apache-2.0.

Modes:
- custom: 9 preset speakers (Ryan/Aiden for English, …), optional natural-language
  emotion `instruct` per generation ("speak excitedly").
- clone: 3-second+ reference clip + its transcript → cloned voice.
  REQUIRES explicit consent (params["consent"] is True); the consent is recorded
  in voice_consents.json. No cloning of public figures — enforced by policy,
  surfaced in the UI.

Long text is chunked by sentence; chunks are concatenated with short pauses.
VRAM policy: only one TTS model resident at a time (the orchestrator + model
manager guarantee this); custom and base models are never loaded together —
the worker unloads the other before loading.
"""
from __future__ import annotations

import os
import re
import time
import uuid

import numpy as np

from ..projects import load_json, project_dir, save_json

CUSTOM_MODEL = "Qwen/Qwen3-TTS-12Hz-0.6B-CustomVoice"
BASE_MODEL = "Qwen/Qwen3-TTS-12Hz-0.6B-Base"
# Allow pre-downloaded local dirs (e.g. models/qwen3-tts-0.6b-custom).
MODEL_DIR_OVERRIDE = {
    CUSTOM_MODEL: os.environ.get("QWEN_TTS_CUSTOM_DIR"),
    BASE_MODEL: os.environ.get("QWEN_TTS_BASE_DIR"),
}
SPEAKERS = [
    ("Ryan", "Dynamic male voice, strong rhythmic drive", "English"),
    ("Aiden", "Sunny American male voice, clear midrange", "English"),
    ("Vivian", "Bright, slightly edgy young female voice", "Chinese"),
    ("Serena", "Warm, gentle young female voice", "Chinese"),
    ("Uncle_Fu", "Seasoned male voice, low mellow timbre", "Chinese"),
    ("Dylan", "Youthful Beijing male voice", "Chinese (Beijing dialect)"),
    ("Eric", "Lively Chengdu male voice", "Chinese (Sichuan dialect)"),
    ("Ono_Anna", "Playful Japanese female voice", "Japanese"),
    ("Sohee", "Warm Korean female voice, rich emotion", "Korean"),
]
LANGUAGES = ["Auto", "Chinese", "English", "Japanese", "Korean", "German",
             "French", "Russian", "Portuguese", "Spanish", "Italian"]

_models: dict[str, object] = {}


def _get(model_id: str):
    """Load one model; unload the other TTS model first (never co-resident)."""
    import torch
    from qwen_tts import Qwen3TTSModel

    for mid in list(_models):
        if mid != model_id:
            del _models[mid]
            if torch.cuda.is_available():
                torch.cuda.empty_cache()
    if model_id not in _models:
        cuda = torch.cuda.is_available()
        source = MODEL_DIR_OVERRIDE.get(model_id) or model_id
        _models[model_id] = Qwen3TTSModel.from_pretrained(
            source,
            device_map="cuda:0" if cuda else "cpu",
            dtype=torch.bfloat16 if cuda else torch.float32,
        )
    return _models[model_id]


def _chunks(text: str, max_chars: int = 220) -> list[str]:
    sentences = [s.strip() for s in re.split(r"(?<=[.!?])\s+", text.strip()) if s.strip()]
    out, cur = [], ""
    for s in sentences:
        if cur and len(cur) + 1 + len(s) > max_chars:
            out.append(cur)
            cur = s
        else:
            cur = (cur + " " + s).strip()
    if cur:
        out.append(cur)
    return out or [text.strip()]


def _concat(wavs: list, sr: int) -> np.ndarray:
    pause = np.zeros(int(sr * 0.3), dtype=np.float32)
    parts = []
    for w in wavs:
        a = np.asarray(w, dtype=np.float32).reshape(-1)
        parts += [a, pause]
    return np.concatenate(parts) if parts else np.zeros(0, dtype=np.float32)


def _record_consent(project_id: str, ref_name: str) -> None:
    rec = load_json(project_id, "voice_consents.json") or {"consents": []}
    rec["consents"].append({
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "reference_file": ref_name,
        "note": "User confirmed they own the rights to this voice / it is their own voice.",
    })
    save_json(project_id, "voice_consents.json", rec)


def run(job, report) -> dict:
    import soundfile as sf

    params = job.params or {}
    text = (params.get("text") or "").strip()
    if not text:
        raise RuntimeError("no text provided")
    mode = params.get("mode", "custom")
    language = params.get("language", "English")
    chunks = _chunks(text)
    sr_out = None
    rendered = []

    if mode == "clone":
        if not params.get("consent"):
            raise RuntimeError("voice cloning requires explicit consent")
        ref_audio, ref_text = params.get("ref_audio"), (params.get("ref_text") or "").strip()
        if not ref_audio or not ref_text:
            raise RuntimeError("cloning needs a reference audio clip and its transcript")
        _record_consent(job.project_id, ref_audio.split("/")[-1])
        model = _get(BASE_MODEL)

        def gen(t):
            wavs, sr = model.generate_voice_clone(
                text=t, language=language, ref_audio=ref_audio, ref_text=ref_text)
            return wavs[0], sr
    else:
        speaker = params.get("speaker", "Ryan")
        instruct = params.get("instruct", "") or ""
        model = _get(CUSTOM_MODEL)

        def gen(t):
            wavs, sr = model.generate_custom_voice(
                text=t, language=language, speaker=speaker, instruct=instruct)
            return wavs[0], sr

    for i, ch in enumerate(chunks):
        w, sr = gen(ch)
        sr_out = sr
        rendered.append(w)
        report(0.05 + 0.9 * (i + 1) / len(chunks))

    audio = _concat(rendered, sr_out)
    out = project_dir(job.project_id) / f"tts_{uuid.uuid4().hex[:8]}.wav"
    sf.write(str(out), audio, sr_out)
    report(1.0)
    return {"file": out.name, "mode": mode, "chunks": len(chunks),
            "duration_sec": round(len(audio) / sr_out, 2),
            "speaker": params.get("speaker") if mode == "custom" else "cloned"}
