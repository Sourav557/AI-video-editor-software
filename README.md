# LocalCut — Free, Local AI Video Editor

> Working title (rename anytime). A fully local, free, open-source AI video editor:
> upload a video → transcription, silence detection, AI clip finding, captions,
> platform-ready exports. **No cloud, no API keys, no watermarks, no accounts.**

**Status: Slice 1 in progress** (upload → transcription → silence detection, in the browser).
This is a large build done in small, verified slices. Each slice is committed and pushed here.

## Quickstart (browser-based — step 1 of the plan)

```bash
# 1. Backend
cd backend
python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
uvicorn app.main:app --host 127.0.0.1 --port 8000

# 2. Frontend (new terminal) — builds the UI the backend serves
cd frontend
npm install
npm run build
```

Open **http://127.0.0.1:8000** → upload a video → **Analyze** → transcript + silence segments.

First run downloads the Whisper `base` model (~150 MB, one-time, then fully offline).

## Architecture

```
User / UI ──▶ conversational agent (later) ──▶ ORCHESTRATOR (job DAG + queue, not an LLM)
                                                    │ negotiates VRAM
                                                    ▼
                          workers: transcribe · silence · (score · cut · caption · render …)
                                                    │
                                              model manager
```

- Backend: FastAPI, local job queue, SQLite later. Frontend: React + Tailwind, served locally.
- Full product spec: [`docs/master-prompt.md`](docs/master-prompt.md) (Ultimate Edition).

## Roadmap

- [x] Slice 0 — repo scaffold, orchestrator skeleton, local dev flow
- [x] Slice 1 — upload → faster-whisper transcription (word timestamps) + silence detection
- [x] Slice 2 — clip quality engine (moment scoring, hooks) + caption burn-in (9:16)
- [x] Slice 3 — multi-platform export presets (9:16 / 16:9 / 1:1 + loudness)
- [x] Slice 4 — Qwen3-TTS voiceover (preset voices + consent-gated voice cloning)
- [x] Slice 5 — SEO/packaging engine (keywords, titles, descriptions, thumbnail text)
- [x] Slice 6 — co-editor agent (chat → plans → calls workers; montage stitching)
- [x] Slice 7 — desktop .exe (Tauri + NSIS installer, PyInstaller backend, CI-built)
- [x] Slice 8 — Studio (Filmora-style layout, timeline, autopilot long-video self-edit)
- [x] Slice 9 — full studio (razor/trim/reorder, undo/redo, clip properties, render_edl)
- [x] Slice 10 — Filmora parity (filmstrip, menu bar, media bin, titles track, transport, timeline persist)
- [x] Slice 11 — keyframed transforms (position/scale/rotation/opacity) + keyframe UI
- [x] Slice 12 — transitions library (xfade crossfades + acrossfade audio, 14 types, timeline ⤨ markers)
- [x] Slice 13 — color panel (exposure/contrast/saturation/temperature/vignette + LUTs)
- [x] Slice 14 — speed ramping (piecewise-constant), reverse playback, freeze frame
- [x] Slice 15 — audio FX (parametric EQ, FFT denoise, volume-automation ducking)
- [ ] Slice 4 — Qwen3-TTS voiceover + type-to-fix
- [ ] Slice 5 — SEO/packaging engine (keywords, titles, descriptions, thumbnails)
- [ ] Slice 6 — editing agent + style profiles
- [ ] **Desktop** — after the browser build is verified: package as a Windows `.exe`
      installer (Tauri + NSIS, with uninstaller)

## License

MIT — see [LICENSE](LICENSE).
Model licenses are tracked in [MODEL_LICENSES.md](MODEL_LICENSES.md):
**Tier A** (permissive, default) / **Tier B** (personal-use opt-in, clearly labeled).
