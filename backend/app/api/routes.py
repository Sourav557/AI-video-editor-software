"""REST API — the same surface the future agent, MCP server, and UI all use."""
from __future__ import annotations

from fastapi import APIRouter, File, HTTPException, UploadFile

from ..orchestrator.queue import orchestrator
from ..projects import (get_video_path, load_json, new_project, project_exists,
                        save_upload)

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
    """Queue the Slice-1 analysis DAG: transcribe + silence (independent)."""
    if not project_exists(pid):
        raise HTTPException(404, "project not found")
    if get_video_path(pid) is None:
        raise HTTPException(400, "no video uploaded for this project")
    t = orchestrator.submit("transcribe", pid, priority=10)
    s = orchestrator.submit("silence", pid, priority=10)
    return {"transcribe_job": t.id, "silence_job": s.id}


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
