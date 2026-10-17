"""Central configuration. Everything local; nothing phones home."""
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
PROJECTS_DIR = DATA_DIR / "projects"
FRONTEND_DIST = BASE_DIR.parent / "frontend" / "dist"

# Slice 1: transcription model (tiny|base|small|medium|large-v3). Downloaded once, then offline.
WHISPER_MODEL = "base"
WHISPER_DEVICE = "auto"  # auto -> cuda if available else cpu

# Silence detection tuning
SILENCE_NOISE_DB = -30
SILENCE_MIN_DURATION = 0.5

for d in (DATA_DIR, PROJECTS_DIR):
    d.mkdir(parents=True, exist_ok=True)
