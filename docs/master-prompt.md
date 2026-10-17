# Master Prompt v2 — ULTIMATE EDITION: Free, Local, Personal-Use AI Video Editor
> One conversational agent. One orchestrator. Many specialized workers. Everything below runs on a single consumer GPU, fully offline (except the opt-in SEO module), completely free.

> Improved from v1 after competitive + technical research (Oct 2026). Changes vs v1 are marked **[NEW]** / **[FIXED]** / **[VERIFY]**.
> Replace `[PRODUCT NAME]` before use. Paste into your AI coding assistant **in stages, not all at once**:
> (1) research + PRD, (2) architecture + schemas, (3) packaging + MVP, (4) quality engine, (5) audio suite, (6) agent + style learning, (7) polish.
> **After each stage: review, test, and sign off before continuing.** Each stage has acceptance criteria below — do not advance a stage that fails its criteria.

## 0. GROUND TRUTHS — verified facts the build must respect (do not re-derive from guesswork)

**[NEW]** Competitive pricing reality, Oct 2026 (why "free" is the moat):
- CapCut: Free / Standard ~$9.99/mo / Pro $19.99/mo ($179.99/yr). Free tier = capped AI uses, watermark on Pro assets. Price doubled in 2025; Trustpilot ~1.3/5 driven by billing complaints. Strengths to match: templates, beat sync, auto-captions (60+ langs), motion tracking, search-by-object.
- Filmora: $49.99/yr personal, ~$79.99 perpetual (version-locked), trial watermarked. 2.9M+ asset library. Ceiling: color grading depth, advanced audio.
- Premiere Pro: $22.99/mo, no perpetual license, 7-day trial. Strengths: ecosystem, plugins, multicam, text-based editing.
- DaVinci Resolve: **free** full NLE (edit/color/Fairlight/Fusion, 4K60); Studio $295 one-time (Neural Engine AI, noise reduction, HDR, collaboration). This is the real free competitor — beat it on AI automation, not on being an NLE.
- Final Cut Pro: $299.99 one-time (Mac only).
- Descript: free 60 min/mo; $16/$24/$50 tiers. Underlord agent, Studio Sound, text-based editing, dubbing.
- OpusClip: free watermarked; Starter $15/mo (150 min). Complaints: credits meter *uploads* not clips, credits expire.
- Vizard: free 60 min/mo (720p); ~$14.50/mo annual. Complaint: paywalls *quantity* of clips found.
- Submagic: ~$19/mo (15 videos). Complaints: no refunds, caption mismatch bugs.
- Riverside: free 2h multitrack; Pro ~$24/mo annual. 4K, separate per-participant tracks, teleprompter, screen share.
- Open-source clippers: SupoClip (AGPL-3.0, self-host free, works with local Ollama), OpenShorts (MIT core), AutoClipper (MIT, Tauri desktop, local Whisper + Ollama, karaoke captions, face-blur).
- vidIQ (the SEO tool to absorb): Free (3 keyword searches/day) / Pro ~$10/mo / Boost ~$49/mo. Feature set to replicate free: keyword volume + competition + overall score, SEO scorecard 0–100 per upload, AI title generator, AI thumbnail maker, competitor tracking, daily ideas. Note: even vidIQ vs TubeBuddy volume numbers disagree with each other — treat all third-party volumes as relative rankings, never exact counts.

**[FIXED]** License audit — verify each at build time, record code license AND weights license separately in `MODEL_LICENSES.md`:
| Component | Status |
|---|---|
| Qwen3-TTS (0.6B/1.7B) | **OK** — Apache 2.0, real model (released Nov 2025/Jan 2026). **Limit: 10 languages only** (EN, ZH, JA, KO, DE, FR, RU, PT, ES, IT). 3-sec cloning, ~4–6 GB VRAM. |
| faster-whisper / WhisperX, PySceneDetect, MediaPipe, CLIP/SigLIP, FAISS, llama.cpp, SAM 2 | **OK** — permissive |
| Demucs | Code MIT **OK**; weights carry dataset terms — **[VERIFY]** per weight file before bundling |
| InsightFace | Code MIT, but **pretrained weights = non-commercial research only** → Tier B only (see §2) |
| Ultralytics YOLO | **AGPL-3.0 (code + weights)** — **[FIXED]** do NOT depend on the `ultralytics` package. Use Apache-2.0 detectors instead: YOLOX, RT-DETR, or MediaPipe. Depending on an AGPL library is the same copyleft problem as copying AGPL code. |
| FLUX.1 (dev) | Non-commercial → Tier B only, or use SDXL (Open RAIL) / Qwen-Image (Apache 2.0) |
| LTX-Video, Wan 2.x | Apache 2.0 **OK** |
| FFmpeg | Ship **LGPL build only** (no GPL x264 — use NVENC/VideoToolbox/MediaFoundation/OpenH264 for H.264) |
| pyannote (diarization) | **[VERIFY]** gating + per-model license at build time; keep a non-gated fallback |
| Fonts/emoji | Bundle OFL fonts only (Inter/Geist, Space Grotesk, JetBrains Mono, **Noto family for 40+ language coverage — budget its disk size**, Noto Color Emoji) |

**[NEW]** The honest performance bar: v1's "first finished short in under 3 minutes after install" is infeasible — model downloads alone are tens of GB. Replace with: installer shows honest download size + time estimates; "first finished short in under 5 minutes **from project open, with models cached**."

---

## 1. ROLE AND VISION

You are a principal software architect, ML engineer, and product designer. Design and build [PRODUCT NAME], a premium AI video editing platform that is **completely free to run, fully local, and open-source-model based**, yet rivals and surpasses OpusClip, Descript, CapCut, Submagic, Vizard, Riverside, Runway, Premiere Pro and DaVinci Resolve **on automation and AI assistance** (it does not need to out-grade Resolve on color science — it needs to make a solo creator 10x faster).

The user uploads a video (or describes what they want). The AI analyzes everything, edits it, writes hooks, adds captions, generates audio, and produces platform-ready videos. Every AI decision is visible, explainable, and reversible. The user can accept the automatic result or take full manual control on a professional timeline.

**[NEW]** Scope honesty rule: this prompt describes a multi-year product. You will build it in gated stages (§14). **No feature enters the MVP unless its quality bar and its evaluation metric are defined first.** Prefer fewer features done excellently over many done poorly — and enforce it: if a feature cannot meet its bar on the 8 GB VRAM tier, it ships as an opt-in "heavy tier" module, not in the default path.

Target users: YouTubers, podcasters, agencies, marketers, course creators, coaches, brands that repurpose long-form content. **Primary v1 persona: a solo creator repurposing long-form video into shorts.**

---

## 2. HARD CONSTRAINTS (override anything that conflicts)

- **ZERO paid APIs, ZERO per-token cost, no mandatory cloud, no API keys required.** Everything runs on the user's machine and works offline after models are downloaded.
- **[FIXED]** License tiers (this product is for **personal use**, which changes what is allowed):
  - **Tier A — default stack, permissive licenses only** (Apache 2.0 / MIT / BSD / OFL / CC0). This is what ships enabled by default.
  - **Tier B — personal-use opt-in, clearly labeled in UI** (non-commercial research weights such as InsightFace models, FLUX.1-dev). Disabled by default; enabling shows a one-time notice stating the non-commercial restriction. Never silently mix Tier B into Tier A.
  - Record code license AND weights license separately for every model in `MODEL_LICENSES.md`.
  - **No AGPL/GPL dependency anywhere** (not copied, not linked, not shelled out to as a required component) — AGPL's network copyleft would infect the whole product. Learn from ideas only; write original code. Ship an LGPL FFmpeg build.
- **[NEW]** Hardware matrix — auto-detect and choose backend, model size, and quantization:
  - NVIDIA CUDA (primary, NVENC encode), Apple Silicon (Metal + MLX path — e.g. mlx-whisper precedent; MPS fallback), AMD ROCm (Linux), Intel Arc/Xe (best-effort), CPU fallback (slow, clearly labeled).
  - VRAM tiers: 8 GB (lite) / 12–16 GB (standard) / 24 GB+ (full). **Disk budget is a first-class constraint too:** the installer must show a per-tier download manifest with sizes (measure, don't guess) and a storage estimator before downloading. Never keep ASR + LLM + TTS + video-gen resident together — model manager with VRAM budgeting, load on demand, unload after use.
- **[NEW]** Packaging: one-click install per OS — Pinokio launcher (Windows/Linux: `pinokio.js`, `install.json`, `start.json`, update/reset scripts) **plus** signed macOS `.dmg` and Linux `.deb`/AppImage. Plan for code-signing/notarization (or document the exact first-launch bypass). Built-in update channel for the app AND a versioned model manifest with rollback.
- **[NEW]** Local-server security: bind to localhost by default; the LAN/mobile review mode requires an auth token (shown as QR/pairing code), auto-expires, and never exposes the API without it.
- URL import (YouTube/Drive/Dropbox/Zoom): support where the platform terms and the user's own content permit; prefer user-owned files. Never present a terms-violating download as a headline feature.
- **[NEW]** If any requirement in this prompt is infeasible or self-contradictory, **say so with evidence and propose the closest feasible alternative** — do not silently ship a broken version of it.

---

## 3. CORE FEATURES

Each feature is tagged **[MVP]**, **[V1]**, or **[V2]**. MVP = the gated first release. V1 = complete solo-creator product. V2 = pro-studio depth.

### 3.1 Capture & ingest [MVP ingest / V2 capture]
- **[MVP]** Upload (resumable, up to 4K; video, images, audio), proxy generation, multi-track audio import, project media bins.
- **[NEW][V2]** Record in-app: screen + webcam + mic capture, **teleprompter**, direct voiceover recording. Descript-style "keep rolling" mode: record now, delete bad takes from the transcript later. (Riverside/Descript parity — the prompt's ingest-only design concedes the entire recording workflow.)

### 3.2 Deep video understanding (analysis engine) [MVP]
- Word-level STT, speaker diarization (50+ languages), scene/shot detection, face/speaker/object tracking, on-screen OCR.
- Audio events: laughter, applause, emphasis, silence, music, energy peaks. Emotion/sentiment curve, topic segmentation, chapters, summary.
- Multimodal moment scoring (transcript + visuals + audio + emotion).
- **One structured analysis JSON consumed by every module. Cache everything** (transcript, embeddings, scenes) so repeat edits are instant.
- **[NEW]** The same analysis pass also emits a **content-repurposing pack**: YouTube chapters, show notes, blog/newsletter draft, per-platform post copy + hashtags (local LLM). One upload → every asset, not just clips.

### 3.3 One-click Auto Edit [MVP core / V1 polish]
- **[MVP]** Silence/filler/bad-take removal with smooth jump cuts; auto captions; clip engine (§5).
- **[V1]** Auto zoom/punch-ins on peaks; multicam switching by active speaker; transcript-matched auto B-roll (bundled CC0 pack + optional Pexels/Pixabay via a free user-supplied key — offline-first); auto SFX/transitions/music with ducking; denoise, voice isolation, EQ, de-ess, de-click/de-plosive, loudness normalization; eye-contact correction; auto color correction; stabilization; log-footage color management.
- **[NEW][V1]** Keying & background: chroma key with spill suppression **plus** AI subject background removal/replacement for video with no green screen (SAM 2 / RMBG-class). CapCut ships this free — so must we, offline.
- **[NEW][V1]** AI smooth slow motion via RIFE-class frame interpolation (**verified MIT license**) with optical-flow speed-ramp easing. CapCut paywalled smooth slow-mo — headline free win.
- **[NEW][V1]** Privacy blur: one-click track-and-blur for faces, license plates, screens.
- **[NEW][V1]** Color match: one-click exposure/white-balance matching across cameras and clips (multicam parity).
- **[NEW][V1]** Script-to-video mode for faceless channels: paste a script → Qwen3-TTS voiceover + auto-assembled visuals (CC0 stock, AI B-roll, kinetic captions) + music → finished video. CapCut Pro parity, free.
- **[NEW]** Don't-overcut rule: silence/filler removal must preserve dramatic and comedic pauses — never cut below a configurable minimum pause inside an emotional beat.
- **[NEW][V1]** **Beat sync**: detect music beats, snap cuts/transitions to beats (CapCut parity — one of its most-used creator features).
- **[NEW][V2]** Restoration: denoise, deband, deflicker, deshake; **AI object removal with tracking** (Filmora parity).
- Style presets: Podcast, Documentary, Hype/Gaming, Educational, Corporate, Cinematic.

### 3.4 Long-to-Short engine [MVP]
- Top-N moments; natural-language clip requests ("every time the guest mentions pricing"); non-linear stitching; per-platform target lengths (15/30/60/90s).
- Performance-**likelihood** score per clip with plain-language explanation + improvement tips (never presented as a prediction).
- Keep the v1 quality-gate philosophy: **"found 4 strong clips" beats faking 10** (this is exactly Vizard's most-hated behavior — paywalling quantity).
- **[NEW]** Platform-variant packs: one strong moment → re-cut per platform (different hook, caption style, pacing, and length for TikTok vs. Reels vs. Shorts vs. X). The engine plans the variants from the analysis JSON; each variant gets its own title/description/thumbnail from the packaging engine (§3.12).

### 3.5 Hook generator [MVP]
- 5+ hook options per clip (question, bold claim, curiosity gap, pattern interrupt, story-start); hook forms incl. re-ordered best line, on-screen text, visual hook, generated voiceover in the creator's cloned voice; hook strength estimate; A/B variants; auto CTA ending.

### 3.6 Captions and subtitles [MVP]
- Transcript editor (edit text → video updates); animated word-by-word captions **including karaoke highlight styles**; keyword emphasis; emojis; 50+ styles; full font/color/stroke/shadow/position/animation/safe-zone control; brand vocabulary; 40+ caption languages with local translation (translation timing re-fit, not just text swap); SRT/VTT + burned-in export; OFL fonts only.
- **[NEW]** Face-aware caption positioning preset (captions avoid covering faces).
- **[NEW]** Social caption-text generator: suggests the written post caption per platform from the transcript's strongest lines (pairs with the §3.12 packaging engine).
- **[NEW]** Speaker-colored subtitles (each speaker their own color, podcast-style), full RTL support (Arabic/Hebrew/Urdu), and **user-extensible filler-word dictionaries per language** — no hardcoded English-only lists, so Romanized Nepali, Hinglish, and code-switched speech work.

### 3.7 Multi-platform reformatting [MVP]
- One-click presets (TikTok, Reels, Shorts, YouTube, LinkedIn, X, Facebook, Snapchat, Pinterest); AI reframing (9:16, 1:1, 4:5, 16:9) with speaker/object tracking; split-screen for screen-share/gameplay; per-platform duration, pacing, caption safe areas, loudness, bitrate, titles, descriptions, hashtags, thumbnails.
- **[NEW]** Platform specs change — store them as a **versioned preset file** the updater can refresh, not hard-coded constants.

### 3.8 Templates & effects library [NEW][V1]
- **[NEW]** Local template pack system: titles, lower-thirds, transitions, effects, caption styles as versioned, importable/exportable packs (CC0 starter pack bundled). This is CapCut/Filmora's biggest retention moat and v1 had no answer to it. Community packs installable from a folder; every pack lists its asset licenses.

### 3.9 Pro timeline & color & audio [V1/V2]
- **[V1]** Brand kit; text-based editing; full manual timeline (multi-track, keyframes, masking, speed ramps, color grading, audio mixer, unlimited undo, non-destructive project JSON/EDL, render on export only).
- **[NEW][V1]** **Color scopes** (waveform, vectorscope, histogram, parade), `.cube` LUT import, HDR pipeline (PQ/HLG) with SDR tone-map export. (Auto color-correction without scopes is a toy — Resolve wins trust with scopes.)
- **[NEW][V1]** **Motion tracking**: one-click "track to object" for text/effects (point + planar), with previous-frame search when objects leave frame. (Premiere's #1 user-requested gap.)
- **[NEW][V2]** Nested sequences, adjustment layers, **multicam editor** (sync by audio, angle switching), transcript-linked markers, ripple/roll/slip/slide tools, proxy toggle, **background render queue + watch-folder auto-ingest**.
- **[NEW][V2]** Audio: sample-accurate engine spec, **sandboxed VST3/AU plugin hosting**, mixer buses, noise-print denoise, dereverb. (Pro editors all host plugins; v1's closed audio chain is a ceiling.)
- **[NEW][V2]** Open video-effect plugin API (sandboxed JS/WASM filters and transitions) so the community can extend effects without forking the app.

### 3.10 Media management [NEW][V1]
- **[NEW]** Bins, smart collections, metadata/labels, duplicate detection, **relink offline media**, one-click **project archive** (collect all files). Unsexy, and exactly what makes a tool trustworthy on real projects.

### 3.11 Publishing, accessibility, collaboration [V1]
- Direct posting/scheduling via user-supplied OAuth (no paid service); local analytics import; shared brand kits; timecoded comments; approval links; version history; XML/EDL/AAF export to Premiere/Final Cut/Resolve.
- **[NEW]** **AI audio-description track** generation (accessibility differentiator — no competitor does this well locally).
- **[NEW]** Export metadata helpers: YouTube chapters upload, end screens/cards templates, thumbnail "test & compare" guidance.
- **[NEW]** Audio-only export (MP3/WAV/FLAC) and **audiogram export** (waveform video rendered from audio) — podcaster parity for audio-first distribution.

### 3.12 SEO, Packaging & Discovery Engine (the vidIQ inside the software) [NEW][V1]
This is the all-in-one creator layer: keyword research, titles, descriptions, and thumbnails for the long video **and every short** — generated from the same analysis pass, free forever (vidIQ charges up to ~$49/mo for its AI title/thumbnail tier).
- **Keyword research engine**: given the transcript/topic, it gathers candidates from keyless public sources (YouTube autocomplete, Google Trends, Reddit/TikTok public trend signals). An **optional user-supplied YouTube Data API key** unlocks official search-volume data — optional, never required, and the module degrades gracefully offline. **This is the ONE module permitted to need internet**; every other feature stays fully offline.
- **Ranked keyword table in the UI**: per keyword — search volume, competition, overall opportunity score, trend sparkline — displayed as a sortable rank list, vidIQ-style. All volumes labeled as estimates/relative rankings, never exact counts.
- **Title generator**: 5+ high-CTR title options per video per platform, each with a score and a one-line reason (curiosity gap, keyword placement, length fit). **Description generator**: SEO-optimized per-platform descriptions with chapters, hashtags, and CTAs. Tags/hashtag sets per platform.
- **Every short gets its own pack**: title + description + hashtags generated per short, tuned to its hook and transcript — not copy-pasted from the long video.
- **Thumbnail generator**: local open image models (Tier A: SDXL-class / Qwen-Image) combined with **frame extraction from the actual video** — the engine picks high-emotion/face-forward frames, then composites thumbnail text in brand fonts within platform safe zones. 3+ variants per video; each scored on a CTR rubric (contrast, face presence, ≤4 words of text, curiosity gap) with a plain-language explanation; one-click A/B variant export.
- **Competitor scan (opt-in, online)**: top-ranking videos for a target keyword summarized for title/thumbnail *patterns* — inspiration, never copying.
- A dedicated **"Publish Prep" screen**: keyword ranks, titles, descriptions, thumbnails, and the upload checklist for the long video and all its shorts in one view.
- **[NEW]** Outlier scan: find breakout videos from small channels in the niche and summarize the *format* patterns (not the content) — vidIQ's killer feature, free.
- **[NEW]** Trend alerts + AI video-idea generator from niche keyword trends (opt-in, online).
- **[NEW]** Best-time-to-post suggestions computed from the user's own imported channel analytics — no cloud account needed.

---

## 4. AUDIO GENERATION MODULE (Qwen3-TTS primary) [MVP voiceover / V1 full]

Qwen3-TTS runs locally behind an internal TTS service with a swappable engine interface. **Verified: Apache 2.0, 0.6B (~2.5 GB disk, ~3.5–4 GB VRAM) / 1.7B (~4.5 GB, ~5–6 GB VRAM), 97 ms first-packet streaming.**
- **[FIXED]** Language reality: Qwen3-TTS supports **10 languages**. Voiceover/dubbing UI must show a per-language capability matrix; dubbing into non-supported languages falls back to a clearly-labeled secondary engine (e.g. CosyVoice/Chatterbox — verify license at build time) or is disabled with an explanation. Never imply "any language."
- Voiceover from script/transcript; **3-second** voice cloning (mandatory consent checkbox + stored consent record; no public figures); Voice Design from text description → per-brand Voice Library; per-sentence emotion/style control via natural language.
- Type-to-fix (splice in cloned voice, matched room tone/prosody); hook voiceover in creator's voice; dubbing (transcribe → local-LLM translate → re-speak in cloned voice → time-fit via stretch + script shortening; optional local lip-sync); multi-speaker podcast mode; long-text chunking with consistent prosody, crossfades, per-line caching.
- Local SFX/music: bundled CC0/commercially-licensed packs with attribution handling + open text-to-music/SFX models (**[VERIFY]** each model's license).
- Ducking under speech; loudness normalization (-14 LUFS social; per-platform targets from the versioned preset file).

---

## 5. CLIP QUALITY ENGINE (the main advantage) [MVP]

Keep v1's 8-step design (candidate generation → deep pass → boundary rules → structure rules → quality gate → explanations → self-critique loop → evaluation harness). Add:
- **[NEW]** Boundary rule: also cut on **beat boundaries** when music-driven (ties to §3.3 beat sync).
- **[NEW]** Anti-Vizard rule: never charge/limit by quantity of candidates found — the gate rejects weak clips, it does not ransom strong ones.
- **[NEW]** Retention feedback loop: import the user's YouTube retention analytics → the scorer learns where *their* audience actually drops off and tunes moment scoring to their channel. No clipper does this; it is a genuine moat.

---

## 6. VISION-CAPABLE EDITING AGENT [V1]

- Local VLM agent watches video and calls editing tools (cut, zoom, caption, B-roll, audio, layout, reframe); chat-to-edit ("make it punchier"); co-editor behavior: preview timeline with every AI decision marked, reversible, approvable.
- **[NEW]** **Risk ladder**: the agent executes low-risk edits directly, but must ask before destructive/irreversible actions (deleting media, overwriting exports). Every agent action carries a one-line "why."
- Local MCP server + REST API; triggers (watch folder, new upload, schedule, webhook); overnight batch mode for whole archives.

### 6.1 The orchestration layer — how everything gets done fast on one GPU [NEW]
Two layers, never confused:
1. **ONE conversational co-editor agent** — the only AI the user talks to (§6 above). It interprets intent and issues tool calls.
2. **The orchestrator** — not an LLM, not conversational: dumb, boring, ultra-reliable scheduling logic. It takes every request (from the agent, the UI, triggers, or the API) and breaks it into jobs. There is no second chat agent anywhere in the system — the §3.12 SEO module is an *engine* (a worker), not an agent.
- **Workers** (specialized, stateless): transcribe, diarize, scene-detect, score, cut, caption, reframe, render, TTS, thumbnail, SEO/packaging, B-roll fetch. Each worker declares its required model + VRAM; the orchestrator negotiates load/unload order with the model manager (§2) so two heavy models never co-reside — this is what makes one-GPU operation safe.
- **Dependency-ordered execution**: every job declares its inputs; the orchestrator topologically sorts the DAG. Nothing runs before its inputs exist — zero wasted GPU cycles on stale work.
- **Pipeline parallelism** (the real speedup): independent stages overlap — FFmpeg renders clip N (CPU) while the caption worker prepares clip N+1 while the LLM scores clip N+2. Priority lanes: interactive/preview jobs preempt overnight batch jobs; the user never waits behind a background queue.
- **Failure handling**: per-job checkpoints, retry with backoff, dead-job detection, **idempotent jobs** (running twice never corrupts state). A worker crash never kills the queue; an orchestrator crash pauses everything safely and resumes on restart — a crash never loses work (§9).
- **Dedup + cache**: content-hash every input; reuse prior results (transcript, embeddings, scenes, scores) instead of recomputing. Analyze once, everywhere.
- **One progress stream** to the UI ("Step 4/9: scoring moments…", never a blank spinner) plus a **decision log** — every job records what it did and why, feeding the explainability rule (§1: every AI action is explainable and reversible).
- **Scaling rule**: on 24 GB+ VRAM the orchestrator may co-schedule two *small* workers (e.g. thumbnail + caption prep); on 8 GB it strictly serializes heavy models. The policy is data-driven from the benchmark table (§10), not hardcoded.

---

## 7. STYLE PROFILES AND FOOTAGE SEARCH [V1]

- Style Profiles: learn per-brand/per-client style from approved projects (layouts, zoom frequency, pacing, caption style, music, B-roll density); refine from keep/move/delete signals; stored locally.
- Footage Search: natural-language search across the library ("where he laughs near the whiteboard") via local CLIP/SigLIP + transcripts + object/scene metadata → timestamped results. (CapCut's "search by objects, dialogue, people" parity.)
- **[V2]** Optional heavy tier: local generative extend (Wan/LTX-Video, Apache 2.0) for B-roll gaps.

---

## 8. OPEN-SOURCE STACK (verify latest best option for each at build time; §0 table is the starting point, not the final word)

Transcription: faster-whisper / WhisperX (word timestamps) → diarization: open model, **[VERIFY]** gating/licensing, keep non-gated fallback. Brain: local Qwen LLM via llama.cpp (prefer llama.cpp over Ollama until Ollama's distribution terms are verified), small + large tiers; Qwen-VL for frames; structured JSON with schema validation. Scene detection: PySceneDetect. Detection/tracking: **YOLOX or RT-DETR (Apache 2.0) or MediaPipe — NOT the Ultralytics package (AGPL-3.0)**; face analysis: MediaPipe default, InsightFace weights only in Tier B. Search: CLIP/SigLIP + FAISS/SQLite-vec. Audio events: open classifiers + librosa. Stems: Demucs (**[VERIFY]** weight terms). Masking: SAM 2 / RMBG-class (**[VERIFY]**). Upscaling: Real-ESRGAN. Thumbnails: SDXL-class (Open RAIL) or Qwen-Image (Apache 2.0); FLUX.1-dev Tier B only. Render: **LGPL FFmpeg build** + GPU encoders (NVENC/QuickSync/VideoToolbox/VAAPI). Backend: Python FastAPI, SQLite (Postgres optional), local job queue (no Redis requirement), React UI served locally, WebCodecs/WebGL timeline.
- **[NEW]** Every model entry in the manifest records: parameter count, quantized size, disk size, VRAM at the chosen quantization, license (code + weights), and which tier enables it.

---

## 9. SPEED, RELIABILITY, UX

- Analyze once, cache everything; edit on proxies; render full quality only on export; resumable jobs with checkpoints — a crash never loses work; honest time estimates; live progress with stage names (never a blank spinner).
- Three modes: Auto (one click) / Assisted (review suggestions) / Pro (full timeline).
- **[FIXED]** "First finished short in under 5 minutes **from project open with models cached**." Installer shows per-tier download manifest with real sizes + time estimates.
- **[NEW]** Project format is **versioned** (`project.json` carries a schema version; migrations run on open; never silently fail on a newer file).
- Dark-first premium UI (Linear/Raycast/Resolve/CapCut polish), light theme, system-follow; LAN/mobile review-and-approve view behind the auth token (§2).
- **[NEW]** First-run experience: guided tutorial project + bundled CC0 sample pack so the "first short" flow is testable in minutes without the user supplying footage.
- **[NEW][V2]** Companion capture app (PWA): record on the phone → auto-ingest to the desktop over LAN; review and approve agent edits from the couch. Honest scope: a companion, not a full mobile NLE — that is a separate multi-year product.
- **[NEW]** No accounts, no logins, no watermarks — ever. Stated product guarantee (CapCut requires login and watermarks free exports).
- **[NEW]** Autosave with versioned backups; offline user manual + in-app searchable help; update checks are manual or opt-in — the app never phones home on its own.

---

## 10. QUALITY EVALUATION [start day one]

- Golden set: 30–50 diverse videos (podcast, interview, vlog, tutorial, gaming, sports, no-dialogue). **[NEW]** Golden-set footage must be CC0 or self-recorded — record its license per clip; never eval on scraped copyrighted content.
- Automated metrics: clip boundary cleanliness, caption WER + sync, **karaoke timing accuracy**, loudness compliance, hook quality score, render correctness, **TTS: speaker similarity + WER on a fixed sentence set**, dubbing lip-drift.
- **[NEW]** Regression gate: no model/prompt change ships if any metric regresses — enforced in CI, not by honor system.
- Local feedback loop (keep/trim/delete signals tune scoring; never uploaded).
- Benchmark table per hardware tier: 60-min video processing time, peak VRAM, **peak disk**, quality score.

---

## 11. TRUST AND SAFETY

- Voice-clone consent flow + stored consent records; no public figures.
- C2PA Content Credentials / AI-generated labels on generated audio/video (on by default, toggleable).
- Copyright-risk music checks; license-clean bundled assets only; every template pack lists asset licenses.
- Privacy: nothing leaves the machine; no telemetry without explicit opt-in (crash reports are local-first, opt-in upload).
- **[NEW]** LAN mode auth token (§2); consent records exportable/deletable by the user.

---

## 12. RESEARCH TASK (do first) [NEW — expanded]

For each of **CapCut, Filmora, Premiere Pro, DaVinci Resolve, Final Cut Pro, Descript, OpusClip, Vizard, Submagic, Riverside, Runway, Captions, VEED, vidIQ, TubeBuddy, Pikzels,** and open-source **SupoClip, OpenShorts, AutoClipper/AutoClip**: record current features, pricing, and user complaints **with citations (source URL + access date)**. Complaint sources must include Trustpilot, G2, and Reddit (r/VideoEditing, r/podcasting, r/creator). Produce:
1. A feature-gap table (what they do / top complaints / where we win).
2. A "moat map": which competitor strengths are structural (templates network effects, recording) vs. replicable locally.
3. Any important feature missing from this prompt — **you are expected to find at least five**; the §3 **[NEW]** items are a floor, not a ceiling.
4. A pricing-pressure note: which paid features users complain most about losing (CapCut's paywalled AI, OpusClip's expiring credits) — these are our headline wins.

---

## 13. DIFFERENTIATION RULES

1. Every feature works fully offline with no API keys.
2. Beat open-source clippers on clip quality, audio generation, and pro-timeline depth.
3. Prefer fewer features done excellently over many done poorly — **enforced by the §1 scope gate**.
4. Every AI action is explainable and reversible.
5. **[NEW]** Never monetize the user's own compute against them: no credit meters, no expiring anything, no quantity paywalls — the anti-OpusClip/Vizard rule is a product principle.
6. **[NEW]** Tier B (personal-use NC models) is always opt-in and labeled; Tier A is always the default.
7. **[NEW]** Packaging is part of the product, not an upsell: keyword research, titles, descriptions, and thumbnails ship free (§3.12) — the $49/mo vidIQ-Boost-shaped hole in every creator's budget is a headline win.
8. **[NEW]** Explicit non-goals (say them out loud so the builder doesn't gold-plate): remote multi-guest recording with relay servers (Riverside's territory — needs hosted infrastructure), real-time multiplayer co-editing (needs cloud infra), and a full mobile NLE (companion app only, §9).

---

## 14. DELIVERABLES (in order — each with acceptance criteria; do not advance on failure)

1. Competitor feature-gap table + moat map (§12), cited.
2. PRD with user stories and **MVP/V1/V2 priorities** (use the tags in §3; anything untagged defaults to V2).
3. Architecture + data-flow diagrams (analysis, edit, render pipelines) incl. VRAM/disk budgets per tier.
4. Analysis JSON schema + project/EDL JSON schema (versioned).
5. AI pipeline design: moment scoring, hook generation, clip quality engine — with prompts.
6. Database schema + API/MCP endpoint list (+ auth rules for LAN).
7. UI wireframes/screen list + **design system + UI kit** (tokens, components, Figma-style markdown spec, themed React/Tailwind implementation, fully offline — no CDN/font requests).
8. **[NEW]** `MODEL_LICENSES.md` (code + weights licenses, tier A/B per model) + model manifest (sizes, VRAM, quantization per tier).
9. Packaging: Pinokio launcher files + macOS `.dmg` + Linux `.deb`/AppImage plan, signing/notarization plan, model manager with VRAM budgeting, Qwen3-TTS service wrapper, update channel (app + model manifest with rollback).
10. Evaluation harness + hardware benchmark table + golden-set license log.
11. **[NEW]** First-run tutorial project + CC0 sample media pack.
12. 6-month roadmap with milestones, mapped to MVP → V1 → V2.
13. **Implement the MVP in this order:** packaging/installer → transcription + captions (incl. karaoke styles) → silence/filler removal → clip quality engine with local-LLM hooks → Qwen3-TTS voiceover + type-to-fix → multi-platform export → **SEO/title/description/thumbnail packaging engine (§3.12)** → content-repurposing pack → agent + style profiles.
14. **[NEW]** Hardware/disk requirements doc + honest installer estimates.

Ask at most 5 clarifying questions only if truly necessary; otherwise state assumptions and proceed. **Challenge infeasible requirements with evidence (§2).** Write clean, tested, documented code.
