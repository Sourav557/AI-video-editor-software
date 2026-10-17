# MODEL_LICENSES.md

Every model used by LocalCut: code license **and** weights license, tracked separately.
Tier A = permissive, enabled by default. Tier B = personal-use opt-in, labeled in UI.

## Tier A (default)

| Model | Code | Weights | Notes |
|---|---|---|---|
| OpenAI Whisper (via faster-whisper) | MIT (faster-whisper) | MIT (OpenAI) | Slice 1: transcription, word timestamps |
| Qwen3-TTS 0.6B (CustomVoice/Base) | Apache 2.0 (qwen-tts pkg) | Apache 2.0 | Slice 4: voiceover + voice cloning; 10 languages only |

## Tier B (personal-use opt-in — disabled by default)

| Model | Code | Weights | Notes |
|---|---|---|---|
| InsightFace pretrained weights | MIT | **Non-commercial research only** | Face analysis; user must opt in with notice |
| FLUX.1-dev | Apache 2.0 (diffusers) | **Non-commercial** | Thumbnail gen alternative; or use SDXL/Qwen-Image (Tier A) |

## Queued for verification (before bundling)

- Demucs weights — MIT code; weight dataset terms to verify per file
- pyannote diarization models — verify gating + per-model license
- RIFE (frame interpolation) — MIT verified Oct 2026
- YOLOX / RT-DETR — Apache 2.0 (Ultralytics YOLO is AGPL-3.0: **do not use**)
