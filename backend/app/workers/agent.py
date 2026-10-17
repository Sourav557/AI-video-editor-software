"""Worker: the co-editor agent (Slice 6).

Runs the conversation loop as a meta-worker: plans with the selected backend
(rule-based by default; Ollama LLM when AGENT_BACKEND=ollama) and executes
tools via direct worker calls. Queued like any other job; the UI polls it.
"""
from __future__ import annotations

from ..agent.loop import run_turn


def run(job, report) -> dict:
    message = ((job.params or {}).get("message") or "").strip()
    if not message:
        raise RuntimeError("empty message")
    return run_turn(job.project_id, message, report)
