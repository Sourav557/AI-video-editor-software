"""The conversation loop: the only AI surface the user talks to.

plan  →  execute tools (direct worker calls, never queued)  →  compose reply.
History lives in data/projects/<pid>/chat.json — plain JSON, user-owned.
"""
from __future__ import annotations

import time

from ..projects import load_json, save_json
from .backends import select_backend
from .tools import TOOLS


def _ctx(project_id: str) -> dict:
    t = load_json(project_id, "transcript.json")
    c = load_json(project_id, "clips.json")
    return {
        "has_transcript": t is not None,
        "segments": len((t or {}).get("segments", [])),
        "clips": len((c or {}).get("clips", [])),
    }


def run_turn(project_id: str, message: str, report) -> dict:
    history = load_json(project_id, "chat.json") or {"messages": []}
    ctx = _ctx(project_id)
    backend, notice = select_backend()

    plan = backend.plan(message, ctx)
    steps = [(t, a) for t, a in plan.get("steps", []) if t in TOOLS]
    results = []
    for i, (tool_name, args) in enumerate(steps):
        tool = TOOLS[tool_name]
        frac = lambda p, i=i: report(0.05 + 0.9 * (i + p) / max(1, len(steps)))
        try:
            res = tool.execute(project_id, args or {}, frac)
        except Exception as e:  # a tool failure never kills the turn
            res = {"error": f"{type(e).__name__}: {e}"}
        results.append({"tool": tool_name, "args": args, "result": res})

    reply = backend.compose(results, ctx)
    # Ollama wrote its own reply during planning; rule backend composes here.
    if getattr(backend, "name", "") == "ollama" and plan.get("_reply") and not results:
        reply = plan["_reply"]
    if notice:
        reply = notice + " " + reply

    now = time.strftime("%Y-%m-%dT%H:%M:%S")
    history["messages"].append({"role": "user", "text": message, "ts": now})
    history["messages"].append({"role": "agent", "text": reply, "ts": now,
                                "backend": getattr(backend, "name", "rule"),
                                "steps": [{"tool": s["tool"], "args": s["args"],
                                           "result": s["result"]}
                                          for s in results]})
    save_json(project_id, "chat.json", history)
    report(1.0)
    return {"reply": reply, "steps": results,
            "backend": getattr(backend, "name", "rule")}
