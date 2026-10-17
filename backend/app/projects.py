"""Project storage helpers: uploads, derived JSON, all under backend/data (git-ignored)."""
from __future__ import annotations
import json
import shutil
import uuid
from pathlib import Path
from .config import PROJECTS_DIR

VIDEO_EXTS = {".mp4", ".mov", ".mkv", ".webm", ".avi", ".m4v"}


def new_project() -> str:
    pid = uuid.uuid4().hex[:12]
    (PROJECTS_DIR / pid).mkdir(parents=True, exist_ok=True)
    return pid


def project_dir(pid: str) -> Path:
    return PROJECTS_DIR / pid


def project_exists(pid: str) -> bool:
    return project_dir(pid).is_dir()


def save_upload(pid: str, filename: str, fileobj) -> Path:
    dest = project_dir(pid) / f"source_{Path(filename).name}"
    with open(dest, "wb") as f:
        shutil.copyfileobj(fileobj, f)
    return dest


def get_video_path(pid: str) -> Path | None:
    d = project_dir(pid)
    for p in sorted(d.iterdir()):
        if p.name.startswith("source_") and p.suffix.lower() in VIDEO_EXTS:
            return p
    return None


def audio_path(pid: str) -> Path:
    return project_dir(pid) / "audio_16k.wav"


def save_json(pid: str, name: str, data: dict) -> Path:
    p = project_dir(pid) / name
    p.write_text(json.dumps(data, indent=1))
    return p


def load_json(pid: str, name: str) -> dict | None:
    p = project_dir(pid) / name
    return json.loads(p.read_text()) if p.exists() else None
