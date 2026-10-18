"""REST API — the same surface the future agent, MCP server, and UI all use."""
from __future__ import annotations

import base64
import os
import re
import shutil
import subprocess
import sys
import time

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse

from ..orchestrator.queue import orchestrator
from ..platforms import PRESET_VERSION, PRESETS
from ..project_settings import get_settings_or_defaults, save_settings
from ..projects import (get_video_path, load_json, new_project, project_dir,
                        project_exists, save_json, save_upload)
from ..workers import codecs as _codecs
from ..workers.tts import LANGUAGES, SPEAKERS

router = APIRouter(prefix="/api")


@router.get("/health")
def health():
    return {"status": "ok", "jobs": len(orchestrator.jobs)}


@router.post("/projects")
def create_project(file: UploadFile = File(...)):
    pid = new_project()
    save_upload(pid, file.filename or "upload", file.file)
    return {"project_id": pid, "filename": file.filename}


@router.get("/projects/{pid}")
def project_info(pid: str):
    if not project_exists(pid):
        raise HTTPException(404, "project not found")
    video = get_video_path(pid)
    jobs = [
        {"id": j.id, "kind": j.kind, "status": j.status, "progress": j.progress,
         "error": j.error}
        for j in orchestrator.for_project(pid)
    ]
    return {"project_id": pid,
            "video": video.name if video else None, "jobs": jobs}


@router.post("/projects/{pid}/analyze")
def analyze(pid: str):
    """Queue the Slice-1 analysis DAG: transcribe + silence (independent),
    then waveform peaks for the timeline (depends on transcribe)."""
    if not project_exists(pid):
        raise HTTPException(404, "project not found")
    if get_video_path(pid) is None:
        raise HTTPException(400, "no video uploaded for this project")
    t = orchestrator.submit("transcribe", pid, priority=10)
    s = orchestrator.submit("silence", pid, priority=10)
    w = orchestrator.submit("waveform", pid, priority=5, depends_on=[t.id])
    f = orchestrator.submit("filmstrip", pid, priority=5)
    return {"transcribe_job": t.id, "silence_job": s.id, "waveform_job": w.id,
            "filmstrip_job": f.id}


@router.get("/jobs/{job_id}")
def job_status(job_id: str):
    j = orchestrator.get(job_id)
    if j is None:
        raise HTTPException(404, "job not found")
    return {"id": j.id, "kind": j.kind, "status": j.status,
            "progress": round(j.progress, 3), "error": j.error,
            "note": j.note or "", "result": j.result}


@router.get("/projects/{pid}/transcript")
def transcript(pid: str):
    if not project_exists(pid):
        raise HTTPException(404, "project not found")
    return {
        "transcript": load_json(pid, "transcript.json"),
        "silence": load_json(pid, "silence.json"),
    }


# ---- Slice 2: clip quality engine + caption burn-in ----

@router.post("/projects/{pid}/clips")
def find_clips(pid: str):
    """Queue the scoring worker. Requires a transcript (run Analyze first)."""
    if not project_exists(pid):
        raise HTTPException(404, "project not found")
    if load_json(pid, "transcript.json") is None:
        raise HTTPException(400, "no transcript yet — run Analyze first")
    job = orchestrator.submit("score", pid, priority=10)
    return {"score_job": job.id}


@router.get("/projects/{pid}/clips")
def get_clips(pid: str):
    if not project_exists(pid):
        raise HTTPException(404, "project not found")
    clips = load_json(pid, "clips.json")
    if clips is None:
        raise HTTPException(404, "no clips yet — run Find clips first")
    return clips


@router.post("/projects/{pid}/clips/{idx}/render")
def render_clip(pid: str, idx: int):
    """Queue a caption burn-in render for one scored clip."""
    if not project_exists(pid):
        raise HTTPException(404, "project not found")
    clips = load_json(pid, "clips.json")
    if not clips or idx >= len(clips["clips"]):
        raise HTTPException(400, "clip not found — run Find clips first")
    job = orchestrator.submit("caption", pid, priority=10,
                              params={"clip_index": idx})
    return {"render_job": job.id, "clip_index": idx}


@router.get("/projects/{pid}/clips/{idx}/file")
def clip_file(pid: str, idx: int):
    if not project_exists(pid):
        raise HTTPException(404, "project not found")
    path = project_dir(pid) / f"clip_{idx}.mp4"
    if not path.exists():
        raise HTTPException(404, "clip not rendered yet")
    return FileResponse(path, media_type="video/mp4", filename=f"clip_{idx}.mp4")


# ---- Slice 3: multi-platform export ----

@router.get("/platforms")
def list_platforms():
    return {"version": PRESET_VERSION, "platforms": PRESETS}


@router.post("/projects/{pid}/export")
def export_clip(pid: str, body: dict):
    """Queue a platform export. Body: {"clip_index": int, "platform": str}."""
    if not project_exists(pid):
        raise HTTPException(404, "project not found")
    platform = body.get("platform", "tiktok")
    if platform not in PRESETS:
        raise HTTPException(400, f"unknown platform; choose from {sorted(PRESETS)}")
    idx = body.get("clip_index")
    clips = load_json(pid, "clips.json")
    if idx is None or not clips or idx >= len(clips["clips"]):
        raise HTTPException(400, "clip not found — run Find clips first")
    job = orchestrator.submit("export", pid, priority=10,
                              params={"clip_index": idx, "platform": platform})
    return {"export_job": job.id, "platform": platform, "clip_index": idx}


@router.get("/projects/{pid}/exports/{filename}")
def export_file(pid: str, filename: str):
    if not project_exists(pid):
        raise HTTPException(404, "project not found")
    if not filename.startswith("export_") or not filename.endswith(".mp4") \
            or "/" in filename or "\\" in filename:
        raise HTTPException(400, "invalid filename")
    path = project_dir(pid) / filename
    if not path.exists():
        raise HTTPException(404, "export not ready yet")
    return FileResponse(path, media_type="video/mp4", filename=filename)


# ---- Slice 4: Qwen3-TTS voice studio ----

@router.get("/tts/voices")
def tts_voices():
    return {
        "engine": "Qwen3-TTS 0.6B (Apache-2.0)",
        "speakers": [{"name": n, "description": d, "native": lang}
                     for n, d, lang in SPEAKERS],
        "languages": LANGUAGES,
    }


@router.post("/projects/{pid}/tts")
def tts_generate(pid: str, body: dict):
    """Preset-speaker voiceover. Body: {text, speaker, language, instruct}."""
    if not project_exists(pid):
        raise HTTPException(404, "project not found")
    text = (body.get("text") or "").strip()
    if not text:
        raise HTTPException(400, "text is required")
    speaker = body.get("speaker", "Ryan")
    if speaker not in [s[0] for s in SPEAKERS]:
        raise HTTPException(400, "unknown speaker")
    job = orchestrator.submit("tts", pid, priority=10, params={
        "mode": "custom", "text": text, "speaker": speaker,
        "language": body.get("language", "English"),
        "instruct": body.get("instruct", "") or "",
    })
    return {"tts_job": job.id}


@router.post("/projects/{pid}/tts/clone")
def tts_clone(pid: str, text: str = Form(...), ref_text: str = Form(...),
              language: str = Form("English"), consent: bool = Form(False),
              ref_audio: UploadFile = File(...)):
    """Voice cloning from a 3s+ reference clip. Consent is mandatory."""
    if not project_exists(pid):
        raise HTTPException(404, "project not found")
    if not consent:
        raise HTTPException(400, "voice cloning requires explicit consent")
    if not text.strip() or not ref_text.strip():
        raise HTTPException(400, "text and ref_text are required")
    dest = project_dir(pid) / f"voice_ref_{uuid4hex()}{_safe_ext(ref_audio.filename)}"
    with open(dest, "wb") as f:
        f.write(ref_audio.file.read())
    job = orchestrator.submit("tts", pid, priority=10, params={
        "mode": "clone", "text": text.strip(), "language": language,
        "ref_audio": str(dest), "ref_text": ref_text.strip(), "consent": True,
    })
    return {"tts_job": job.id}


def uuid4hex() -> str:
    import uuid
    return uuid.uuid4().hex[:8]


def _safe_ext(filename: str | None) -> str:
    ext = (filename or "").rsplit(".", 1)[-1].lower() if "." in (filename or "") else ""
    return f".{ext}" if ext in {"wav", "mp3", "m4a", "ogg", "flac"} else ".wav"


@router.get("/projects/{pid}/tts/{filename}")
def tts_file(pid: str, filename: str):
    if not project_exists(pid):
        raise HTTPException(404, "project not found")
    if not filename.startswith("tts_") or not filename.endswith(".wav") \
            or "/" in filename or "\\" in filename:
        raise HTTPException(400, "invalid filename")
    path = project_dir(pid) / filename
    if not path.exists():
        raise HTTPException(404, "voiceover not ready yet")
    return FileResponse(path, media_type="audio/wav", filename=filename)


# ---- Slice 5: SEO / packaging / discovery engine ----

@router.post("/projects/{pid}/seo")
def seo_generate(pid: str):
    """Queue the packaging worker. Requires a transcript (run Analyze first)."""
    if not project_exists(pid):
        raise HTTPException(404, "project not found")
    if load_json(pid, "transcript.json") is None:
        raise HTTPException(400, "no transcript yet — run Analyze first")
    job = orchestrator.submit("seo", pid, priority=10)
    return {"seo_job": job.id}


@router.get("/projects/{pid}/seo")
def seo_get(pid: str):
    if not project_exists(pid):
        raise HTTPException(404, "project not found")
    seo = load_json(pid, "seo.json")
    if seo is None:
        raise HTTPException(404, "no packaging yet — run Publish prep first")
    return seo


# ---- Slice 6: the co-editor agent ----

@router.post("/projects/{pid}/chat")
def chat(pid: str, body: dict):
    """Send a message to the co-editor agent. Returns a job id to poll."""
    if not project_exists(pid):
        raise HTTPException(404, "project not found")
    message = (body.get("message") or "").strip()
    if not message:
        raise HTTPException(400, "message is required")
    job = orchestrator.submit("agent", pid, priority=20,
                              params={"message": message})
    return {"chat_job": job.id}


@router.get("/projects/{pid}/chat")
def chat_history(pid: str):
    if not project_exists(pid):
        raise HTTPException(404, "project not found")
    return load_json(pid, "chat.json") or {"messages": []}


@router.get("/projects/{pid}/montage/{filename}")
def montage_file(pid: str, filename: str):
    if not project_exists(pid):
        raise HTTPException(404, "project not found")
    if not filename.startswith("montage_") or not filename.endswith(".mp4") \
            or "/" in filename or "\\" in filename:
        raise HTTPException(400, "invalid filename")
    path = project_dir(pid) / filename
    if not path.exists():
        raise HTTPException(404, "montage not ready yet")
    return FileResponse(path, media_type="video/mp4", filename=filename)


# ---- Slice 8: studio (timeline) + autopilot (long-video self-edit) ----

@router.get("/projects/{pid}/source/file")
def source_file(pid: str):
    """Stream the uploaded source video (preview monitor)."""
    if not project_exists(pid):
        raise HTTPException(404, "project not found")
    video = get_video_path(pid)
    if video is None:
        raise HTTPException(404, "no video uploaded")
    return FileResponse(video, media_type="video/mp4",
                        filename=f"source{video.suffix}")


@router.get("/projects/{pid}/waveform")
def get_waveform(pid: str):
    if not project_exists(pid):
        raise HTTPException(404, "project not found")
    wf = load_json(pid, "waveform.json")
    if wf is None:
        raise HTTPException(404, "no waveform yet — run Analyze first")
    return wf


@router.post("/projects/{pid}/autopilot")
def autopilot_start(pid: str, body: dict):
    """Queue the autopilot long-video self-edit."""
    if not project_exists(pid):
        raise HTTPException(404, "project not found")
    if get_video_path(pid) is None:
        raise HTTPException(400, "no video uploaded for this project")
    job = orchestrator.submit("autopilot", pid, priority=15, params={
        "remove_silence": body.get("remove_silence", True),
        "silence_pad": float(body.get("silence_pad", 0.2)),
        "remove_fillers": body.get("remove_fillers", False),
        "captions": body.get("captions", True),
    })
    return {"autopilot_job": job.id}


@router.get("/projects/{pid}/autopilot")
def autopilot_get(pid: str):
    if not project_exists(pid):
        raise HTTPException(404, "project not found")
    edl = load_json(pid, "autopilot_edl.json")
    if edl is None:
        raise HTTPException(404, "no autopilot edit yet")
    return edl


@router.get("/projects/{pid}/autopilot/file")
def autopilot_file(pid: str):
    if not project_exists(pid):
        raise HTTPException(404, "project not found")
    path = project_dir(pid) / "autopilot.mp4"
    if not path.exists():
        raise HTTPException(404, "autopilot output not ready yet")
    return FileResponse(path, media_type="video/mp4", filename="autopilot.mp4")


# ---- Slice 9: full studio — render the user's timeline edit ----

@router.post("/projects/{pid}/edit/render")
def edit_render(pid: str, body: dict):
    """Render an explicit block list from the timeline editor.

    Optional Slice-18 codec options: {"codec", "crf", "preset", "profile"}.
    Without them the default h264 path runs exactly as before."""
    if not project_exists(pid):
        raise HTTPException(404, "project not found")
    blocks = body.get("blocks") or []
    if not blocks:
        raise HTTPException(400, "empty timeline")
    job = orchestrator.submit("render_edl", pid, priority=15, params={
        "blocks": blocks,
        "captions": body.get("captions", True),
        "titles": body.get("titles") or [],
        **_export_opts_or_400(body),
    })
    return {"render_job": job.id}


def _export_opts_or_400(body: dict) -> dict:
    """Sanitize optional codec options for /edit/render; {} when absent.

    Unknown codecs and unavailable encoders (e.g. AV1 on a slim ffmpeg
    build) become clean 400s here so the job never starts doomed."""
    if not any(k in body for k in ("codec", "crf", "preset", "profile")):
        return {}
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        raise HTTPException(500, "ffmpeg not found on PATH")
    try:
        spec = _codecs.clean_export_spec(body.get("codec", "h264"),
                                         body.get("crf"), body.get("preset"),
                                         body.get("profile"))
    except ValueError as e:
        raise HTTPException(400, str(e))
    ok, msg = _codecs.availability(ffmpeg, spec["codec"])
    if not ok:
        raise HTTPException(400, msg)
    return {"codec": spec["codec"], "crf": spec["crf"],
            "preset": spec["preset"], "profile": spec["profile"]}


@router.post("/projects/{pid}/edit/batch")
def edit_batch(pid: str, body: dict):
    """Queue a batch export: render the timeline ONCE, then transcode one
    file per item. Body: {blocks, captions?, titles?, items: [{codec, crf?, preset?, profile?}]}."""
    if not project_exists(pid):
        raise HTTPException(404, "project not found")
    blocks = body.get("blocks") or []
    if not blocks:
        raise HTTPException(400, "empty timeline")
    items = body.get("items")
    if not items or not isinstance(items, list):
        raise HTTPException(400, "items must be a non-empty list")
    if len(items) > 8:
        raise HTTPException(400, "max 8 batch items per job")
    # Validate every codec + encoder availability up front (fail fast).
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        raise HTTPException(500, "ffmpeg not found on PATH")
    for it in items:
        if not isinstance(it, dict):
            raise HTTPException(400, "each batch item must be an object")
        try:
            spec = _codecs.clean_export_spec(it.get("codec", "h264"),
                                             it.get("crf"), it.get("preset"),
                                             it.get("profile"))
        except ValueError as e:
            raise HTTPException(400, str(e))
        ok, msg = _codecs.availability(ffmpeg, spec["codec"])
        if not ok:
            raise HTTPException(400, msg)
    job = orchestrator.submit("batch_export", pid, priority=15, params={
        "blocks": blocks,
        "captions": body.get("captions", True),
        "titles": body.get("titles") or [],
        "items": items,
    })
    return {"batch_job": job.id, "count": len(items)}


_EXPORT_FILE_EXTS = {".mp4": "video/mp4", ".mov": "video/quicktime",
                     ".webm": "video/webm", ".gif": "image/gif",
                     ".mp3": "audio/mpeg", ".wav": "audio/wav"}


@router.get("/projects/{pid}/edit/files/{filename}")
def edit_export_file(pid: str, filename: str):
    """Download a codec/batch export (edit_hevc.mp4, edit.webm, edit.gif, edit.mp3…)."""
    if not project_exists(pid):
        raise HTTPException(404, "project not found")
    if (not filename.startswith("edit_") or "/" in filename or "\\" in filename
            or ".." in filename):
        raise HTTPException(400, "invalid filename")
    ext = "." + filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    if ext not in _EXPORT_FILE_EXTS:
        raise HTTPException(400, "invalid filename")
    path = project_dir(pid) / filename
    if not path.exists():
        raise HTTPException(404, "export not ready yet")
    return FileResponse(path, media_type=_EXPORT_FILE_EXTS[ext], filename=filename)


@router.get("/export/codecs")
def export_codecs():
    """Slice 18: codec catalog for the export UI (labels, CRF ranges, presets)."""
    return {"codecs": _codecs.describe()}


@router.get("/projects/{pid}/settings")
def settings_get(pid: str):
    """Project settings (canvas + fps) for the UI; defaults when unsaved."""
    if not project_exists(pid):
        raise HTTPException(404, "project not found")
    return get_settings_or_defaults(pid)


@router.post("/projects/{pid}/settings")
def settings_save(pid: str, body: dict):
    """Save project settings. Body: {aspect?, width?, height?, fps?}."""
    if not project_exists(pid):
        raise HTTPException(404, "project not found")
    return save_settings(pid, body)


@router.get("/projects/{pid}/edit")
def edit_get(pid: str):
    if not project_exists(pid):
        raise HTTPException(404, "project not found")
    edl = load_json(pid, "edit_edl.json")
    if edl is None:
        raise HTTPException(404, "no manual edit yet")
    return edl


@router.get("/projects/{pid}/edit/file")
def edit_file(pid: str):
    if not project_exists(pid):
        raise HTTPException(404, "project not found")
    path = project_dir(pid) / "edit.mp4"
    if not path.exists():
        raise HTTPException(404, "edit output not ready yet")
    return FileResponse(path, media_type="video/mp4", filename="edit.mp4")


# ---- Slice 13: color panel — list shipped .cube LUTs ----

@router.get("/luts")
def list_luts():
    """Names of .cube LUTs shipped in backend/luts/ (for the color panel dropdown)."""
    import re
    # backend/luts lives next to backend/app
    lut_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "luts"))
    names = []
    if os.path.isdir(lut_dir):
        for f in sorted(os.listdir(lut_dir)):
            if re.match(r"^[A-Za-z0-9_-]+\.cube$", f) and os.path.isfile(os.path.join(lut_dir, f)):
                names.append(f)
    return {"luts": names}


# ---- Slice 10: Filmora parity — filmstrip, project info, timeline persist ----

@router.get("/projects/{pid}/filmstrip")
def filmstrip_get(pid: str):
    if not project_exists(pid):
        raise HTTPException(404, "project not found")
    fs = load_json(pid, "filmstrip.json")
    if fs is None:
        raise HTTPException(404, "no filmstrip yet — run Analyze first")
    return fs


@router.get("/projects/{pid}/filmstrip/{name}")
def filmstrip_thumb(pid: str, name: str):
    if not project_exists(pid):
        raise HTTPException(404, "project not found")
    if not name.startswith("thumb_") or not name.endswith(".jpg") \
            or "/" in name or "\\" in name:
        raise HTTPException(400, "invalid thumbnail name")
    path = project_dir(pid) / "filmstrip" / name
    if not path.exists():
        raise HTTPException(404, "thumbnail not found")
    return FileResponse(path, media_type="image/jpeg")


@router.get("/projects/{pid}/info")
def project_info(pid: str):
    """Resolution, fps, duration… — the Project Info panel."""
    if not project_exists(pid):
        raise HTTPException(404, "project not found")
    video = get_video_path(pid)
    if video is None:
        raise HTTPException(404, "no video uploaded")
    import json as _json
    import shutil as _shutil
    import subprocess as _sp
    ffprobe = _shutil.which("ffprobe")
    if not ffprobe:
        raise HTTPException(500, "ffprobe not found")
    p = _sp.run([ffprobe, "-v", "error", "-select_streams", "v:0",
                 "-show_entries", "stream=width,height,r_frame_rate,duration,pix_fmt",
                 "-show_entries", "format=duration,size",
                 "-of", "json", str(video)],
                capture_output=True, text=True)
    info = _json.loads(p.stdout or "{}")
    st = (info.get("streams") or [{}])[0]
    fmt = info.get("format") or {}
    fps = st.get("r_frame_rate", "0/1")
    try:
        num, den = fps.split("/")
        fps_f = round(int(num) / int(den), 2) if int(den) else 0
    except Exception:
        fps_f = 0
    size_mb = round(int(fmt.get("size", 0)) / 1e6, 1)
    return {"filename": video.name, "width": st.get("width"),
            "height": st.get("height"), "fps": fps_f,
            "duration": round(float(fmt.get("duration") or st.get("duration") or 0), 1),
            "pix_fmt": st.get("pix_fmt"), "size_mb": size_mb}


@router.get("/projects/{pid}/audio")
def audio_list(pid: str):
    """Voiceover WAVs (Slice 4 TTS + Slice 17 mic recordings) for the Audio tab."""
    if not project_exists(pid):
        raise HTTPException(404, "project not found")
    files = sorted(p.name for p in project_dir(pid).iterdir()
                   if _is_audio_clip(p.name))
    return {"files": files}


_AUDIO_EXTS = {"wav", "mp3", "m4a", "ogg", "flac", "webm"}
_AUDIO_PREFIXES = ("tts_", "vo_")
_AUDIO_MIMES = {"wav": "audio/wav", "mp3": "audio/mpeg", "m4a": "audio/mp4",
                "ogg": "audio/ogg", "flac": "audio/flac", "webm": "audio/webm"}


def _is_audio_clip(name: str) -> bool:
    """Slice 17: an audio file belongs in the bin iff it was generated by the
    app (tts_*/vo_ prefix) and has an allowed audio extension."""
    if not name.startswith(_AUDIO_PREFIXES) or "/" in name or "\\" in name:
        return False
    ext = name.rsplit(".", 1)[-1].lower() if "." in name else ""
    return ext in _AUDIO_EXTS


@router.get("/projects/{pid}/audio/{name}")
def audio_file(pid: str, name: str):
    if not project_exists(pid):
        raise HTTPException(404, "project not found")
    if not _is_audio_clip(name):
        raise HTTPException(400, "invalid audio name")
    path = project_dir(pid) / name
    if not path.exists():
        raise HTTPException(404, "audio not found")
    ext = name.rsplit(".", 1)[-1].lower()
    return FileResponse(path, media_type=_AUDIO_MIMES[ext], filename=name)


@router.get("/projects/{pid}/timeline")
def timeline_get(pid: str):
    if not project_exists(pid):
        raise HTTPException(404, "project not found")
    tl = load_json(pid, "timeline.json")
    if tl is None:
        raise HTTPException(404, "no saved timeline")
    return tl


@router.post("/projects/{pid}/timeline")
def timeline_save(pid: str, body: dict):
    if not project_exists(pid):
        raise HTTPException(404, "project not found")
    markers = body.get("markers") or []
    if not isinstance(markers, list):
        raise HTTPException(400, "markers must be a list")
    clean = []
    for m in markers[:200]:  # cap: 200 markers max
        if not isinstance(m, dict):
            continue
        try:
            t = float(m.get("t", 0))
        except (TypeError, ValueError):
            continue
        label = str(m.get("label") or "")[:60]
        clean.append({"id": str(m.get("id") or f"m{len(clean)}"),
                      "t": max(0.0, t), "label": label})
    save_json(pid, "timeline.json",
              {"blocks": body.get("blocks") or [],
               "titles": body.get("titles") or [],
               "markers": clean})
    return {"ok": True}


# ---- Slice 17: voiceover mic recording, screen capture, snapshot, markers ----

@router.post("/projects/{pid}/audio/upload")
def audio_upload(pid: str, file: UploadFile = File(...)):
    """Save a mic-recorded voiceover (MediaRecorder output). The app names it
    vo_<timestamp>.<ext>; it then shows up in the Audio tab's list."""
    if not project_exists(pid):
        raise HTTPException(404, "project not found")
    ext = (file.filename or "").rsplit(".", 1)[-1].lower() \
        if "." in (file.filename or "") else ""
    if ext not in _AUDIO_EXTS:
        raise HTTPException(400,
                            f"unsupported audio type; use one of {sorted(_AUDIO_EXTS)}")
    data = file.file.read()
    if len(data) > 200_000_000:  # 200 MB cap
        raise HTTPException(413, "audio too large (200 MB cap)")
    name = f"vo_{int(time.time() * 1000)}.{ext}"
    (project_dir(pid) / name).write_bytes(data)
    result: dict = {"file": name}
    dur = _wav_duration(project_dir(pid) / name) if ext == "wav" else None
    if dur is not None:
        result["duration"] = dur
    return result


def _wav_duration(path) -> float | None:
    """Best-effort WAV duration; None when the file isn't parseable as WAV."""
    try:
        import wave
        with wave.open(str(path), "rb") as w:
            return round(w.getnframes() / w.getframerate(), 2)
    except Exception:
        return None


def _screen_cmd(platform: str, region: str | None, fps: int, out: str) -> list[str]:
    """Pure function: ffmpeg screen-capture arg list for a platform.

    region is "WxH" or None (full screen). Device indices vary per machine —
    darwin "1" is usually the display; run
    `ffmpeg -f avfoundation -list_devices true -i ""` to verify.
    """
    cmd = ["ffmpeg", "-y"]
    if region:
        cmd += ["-video_size", region]
    cmd += ["-framerate", str(fps)]
    if platform == "win32":
        cmd += ["-f", "gdigrab", "-i", "desktop"]
    elif platform == "darwin":
        cmd += ["-f", "avfoundation", "-i", "1"]
    else:  # linux
        cmd += ["-f", "x11grab", "-i", ":0.0"]
    cmd += ["-c:v", "libx264", "-pix_fmt", "yuv420p", "-preset", "ultrafast",
            out]
    return cmd


# pid -> {"proc": Popen, "file": str, "started": float}. Raw subprocess in the
# API process (open-ended, so NOT an orchestrator job — see queue.py).
_recordings: dict[str, dict] = {}


def _prune_dead_recording(pid: str) -> None:
    rec = _recordings.get(pid)
    if rec is not None and rec["proc"].poll() is not None:
        _recordings.pop(pid, None)


@router.post("/projects/{pid}/record/start")
def record_start(pid: str, body: dict):
    """Start screen capture as a background ffmpeg subprocess.
    Body (optional): {"region": "1280x720", "fps": 30}."""
    if not project_exists(pid):
        raise HTTPException(404, "project not found")
    _prune_dead_recording(pid)
    if pid in _recordings:
        raise HTTPException(409, "already recording")
    if shutil.which("ffmpeg") is None:
        raise HTTPException(500, "ffmpeg not found on this machine")
    if sys.platform.startswith("linux") and not os.environ.get("DISPLAY"):
        raise HTTPException(
            500, "no display found ($DISPLAY is not set) — screen capture "
                 "needs a running X session")
    region = body.get("region")
    if region is not None:
        m = re.fullmatch(r"(\d{1,5})x(\d{1,5})", str(region))
        if not m or int(m.group(1)) > 8192 or int(m.group(2)) > 8192:
            raise HTTPException(400, 'region must look like "1280x720"')
        region = f"{m.group(1)}x{m.group(2)}"
    try:
        fps = int(body.get("fps", 30))
    except (TypeError, ValueError):
        raise HTTPException(400, "fps must be an integer")
    if not 1 <= fps <= 60:
        raise HTTPException(400, "fps must be 1–60")
    name = f"screen_{int(time.time() * 1000)}.mp4"
    out = str(project_dir(pid) / name)
    cmd = _screen_cmd(sys.platform, region, fps, out)
    try:
        proc = subprocess.Popen(cmd, stdin=subprocess.PIPE,
                                stdout=subprocess.DEVNULL,
                                stderr=subprocess.DEVNULL)
    except OSError as e:
        raise HTTPException(500, f"could not launch ffmpeg: {e}")
    # Fail fast: if the capture device is unusable, ffmpeg exits immediately.
    time.sleep(0.8)
    if proc.poll() is not None:
        raise HTTPException(
            500, f"screen capture failed to start (ffmpeg exit "
                 f"{proc.returncode}) — no usable capture device")
    _recordings[pid] = {"proc": proc, "file": name, "started": time.time()}
    return {"recording": name}


@router.post("/projects/{pid}/record/stop")
def record_stop(pid: str):
    """Gracefully stop the capture ("q" on stdin, then terminate fallback)."""
    if not project_exists(pid):
        raise HTTPException(404, "project not found")
    rec = _recordings.get(pid)
    if rec is None or rec["proc"].poll() is not None:
        _recordings.pop(pid, None)
        raise HTTPException(404, "nothing recording")
    proc = rec["proc"]
    try:
        proc.stdin.write(b"q")
        proc.stdin.flush()
    except Exception:
        pass
    try:
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        proc.terminate()
        try:
            proc.wait(timeout=3)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait()
    _recordings.pop(pid, None)
    ok = (project_dir(pid) / rec["file"]).exists()
    return {"file": rec["file"],
            "duration": round(time.time() - rec["started"], 1),
            "ok": ok}


@router.get("/projects/{pid}/record/status")
def record_status(pid: str):
    if not project_exists(pid):
        raise HTTPException(404, "project not found")
    rec = _recordings.get(pid)
    if rec is not None and rec["proc"].poll() is None:
        return {"recording": True, "file": rec["file"],
                "elapsed": round(time.time() - rec["started"], 1)}
    _recordings.pop(pid, None)
    return {"recording": False}


@router.get("/projects/{pid}/recordings")
def recording_list(pid: str):
    """Screen captures for the Media tab."""
    if not project_exists(pid):
        raise HTTPException(404, "project not found")
    files = sorted(p.name for p in project_dir(pid).iterdir()
                   if p.name.startswith("screen_") and p.suffix == ".mp4")
    return {"files": files}


@router.get("/projects/{pid}/recordings/{name}")
def recording_file(pid: str, name: str):
    if not project_exists(pid):
        raise HTTPException(404, "project not found")
    if not name.startswith("screen_") or not name.endswith(".mp4") \
            or "/" in name or "\\" in name:
        raise HTTPException(400, "invalid recording name")
    path = project_dir(pid) / name
    if not path.exists():
        raise HTTPException(404, "recording not found")
    return FileResponse(path, media_type="video/mp4", filename=name)


@router.post("/projects/{pid}/snapshot")
def snapshot_save(pid: str, body: dict):
    """Save a preview-canvas snapshot. Body: {"image": dataURL(png)}.
    20 MB cap; PNG magic bytes verified."""
    if not project_exists(pid):
        raise HTTPException(404, "project not found")
    image = body.get("image") or ""
    if not isinstance(image, str) or not image.startswith("data:image/png;base64,"):
        raise HTTPException(400, "image must be a PNG dataURL")
    if len(image) > 28_000_000:  # ~20 MB of binary once decoded
        raise HTTPException(413, "snapshot too large (20 MB cap)")
    try:
        raw = base64.b64decode(image.split(",", 1)[1], validate=True)
    except Exception:
        raise HTTPException(400, "image is not valid base64")
    if not raw.startswith(b"\x89PNG\r\n\x1a\n"):
        raise HTTPException(400, "image is not a PNG")
    name = f"snapshot_{int(time.time() * 1000)}.png"
    (project_dir(pid) / name).write_bytes(raw)
    return {"file": name}


@router.get("/projects/{pid}/snapshots")
def snapshot_list(pid: str):
    """Snapshots for the Media tab."""
    if not project_exists(pid):
        raise HTTPException(404, "project not found")
    files = sorted(p.name for p in project_dir(pid).iterdir()
                   if p.name.startswith("snapshot_") and p.suffix == ".png")
    return {"files": files}


@router.get("/projects/{pid}/snapshots/{name}")
def snapshot_file(pid: str, name: str):
    if not project_exists(pid):
        raise HTTPException(404, "project not found")
    if not name.startswith("snapshot_") or not name.endswith(".png") \
            or "/" in name or "\\" in name:
        raise HTTPException(400, "invalid snapshot name")
    path = project_dir(pid) / name
    if not path.exists():
        raise HTTPException(404, "snapshot not found")
    return FileResponse(path, media_type="image/png", filename=name)
