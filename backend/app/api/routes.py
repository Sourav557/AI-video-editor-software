"""REST API — the same surface the future agent, MCP server, and UI all use."""
from __future__ import annotations

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse

from ..orchestrator.queue import orchestrator
from ..platforms import PRESET_VERSION, PRESETS
from ..projects import (get_video_path, load_json, new_project, project_dir,
                        project_exists, save_upload)
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
    return {"transcribe_job": t.id, "silence_job": s.id, "waveform_job": w.id}


@router.get("/jobs/{job_id}")
def job_status(job_id: str):
    j = orchestrator.get(job_id)
    if j is None:
        raise HTTPException(404, "job not found")
    return {"id": j.id, "kind": j.kind, "status": j.status,
            "progress": round(j.progress, 3), "error": j.error,
            "result": j.result}


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
