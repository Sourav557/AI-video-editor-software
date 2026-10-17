"""LocalCut backend — FastAPI + orchestrator, served on localhost.

Run:  uvicorn app.main:app --host 127.0.0.1 --port 8000   (from backend/)
Then open http://127.0.0.1:8000 — the React UI (frontend/dist) is served here.
"""
from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from . import workers  # noqa: F401  (self-registers with the orchestrator)
from .api.routes import router
from .config import FRONTEND_DIST
from .net import sanitize_proxy_env
from .orchestrator.runner import start as start_orchestrator


@asynccontextmanager
async def lifespan(app: FastAPI):
    sanitize_proxy_env()
    start_orchestrator()
    yield


app = FastAPI(title="LocalCut", version="0.1.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://127.0.0.1:5173", "http://localhost:5173",
        # Tauri desktop shell
        "http://tauri.localhost", "tauri://localhost",
    ],
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(router)

if FRONTEND_DIST.is_dir():
    app.mount("/", StaticFiles(directory=str(FRONTEND_DIST), html=True), name="frontend")
