"""Starts the orchestrator loop on a daemon thread at app startup."""
import threading
from .queue import orchestrator


def start() -> threading.Thread:
    t = threading.Thread(target=orchestrator.run_forever, daemon=True, name="orchestrator")
    t.start()
    return t
