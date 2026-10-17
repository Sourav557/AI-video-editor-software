"""Agent tool registry.

Each tool wraps a worker run() function DIRECTLY. The orchestrator is
single-threaded: an agent meta-worker that submitted sub-jobs to the queue
and waited would deadlock. Direct calls keep the DAG honest — the agent is
just a planner, the orchestrator stays the only scheduler.
"""
from __future__ import annotations

import importlib
import types

from ..projects import load_json


def _run_worker(name: str, project_id: str, params: dict, report) -> dict:
    mod = importlib.import_module(f"app.workers.{name}")
    job = types.SimpleNamespace(project_id=project_id, params=params)
    return mod.run(job, report) or {}


class Tool:
    def __init__(self, name: str, description: str, args_hint: str, execute):
        self.name = name
        self.description = description
        self.args_hint = args_hint
        self.execute = execute


def _t_analyze(pid, args, report):
    _run_worker("transcribe", pid, {}, lambda p: report(p * 0.5))
    _run_worker("silence", pid, {}, lambda p: report(0.5 + p * 0.5))
    d = load_json(pid, "transcript.json") or {}
    return {"segments": len(d.get("segments", [])),
            "words": d.get("word_count", 0),
            "language": d.get("language", "?")}


def _t_find_clips(pid, args, report):
    r = _run_worker("score", pid, {}, report)
    return {"clips": len(r.get("clips", [])),
            "message": r.get("message", ""),
            "top": [{"index": c["index"], "score": c["score"],
                     "hook": c["hook_text"][:60]} for c in r.get("clips", [])[:3]]}


def _t_render_clip(pid, args, report):
    idx = int(args.get("clip_index", 0))
    r = _run_worker("caption", pid, {"clip_index": idx}, report)
    return {"file": r.get("file"), "clip_index": idx}


def _t_export_clip(pid, args, report):
    idx = int(args.get("clip_index", 0))
    platform = args.get("platform", "tiktok")
    r = _run_worker("export", pid, {"clip_index": idx, "platform": platform}, report)
    return {"file": r.get("file"), "platform": platform, "clip_index": idx}


def _t_montage(pid, args, report):
    r = _run_worker("montage", pid,
                    {"clip_indices": args.get("clip_indices"),
                     "platform": args.get("platform", "tiktok")}, report)
    return {"file": r.get("file"), "clips": r.get("clips"),
            "platform": r.get("platform"), "duration": r.get("duration")}


def _t_voiceover(pid, args, report):
    text = (args.get("text") or "").strip()
    if not text:
        return {"error": "no text given"}
    r = _run_worker("tts", pid,
                    {"mode": "custom", "text": text,
                     "speaker": args.get("speaker", "Ryan"),
                     "language": args.get("language", "English"),
                     "instruct": args.get("instruct", "")}, report)
    return {"file": r.get("file"), "duration_sec": r.get("duration_sec")}


def _t_packaging(pid, args, report):
    r = _run_worker("seo", pid, {}, report)
    return {"keywords": r.get("keywords"), "titles": r.get("titles"),
            "clips_packaged": r.get("clips_packaged")}


def _t_autopilot(pid, args, report):
    r = _run_worker("autopilot", pid,
                    {"remove_silence": args.get("remove_silence", True),
                     "remove_fillers": args.get("remove_fillers", False),
                     "captions": args.get("captions", True)}, report)
    return {"file": r.get("file"), "kept": r.get("kept_seconds"),
            "removed": r.get("removed_seconds"), "cuts": r.get("cuts")}


def _t_status(pid, args, report):
    t = load_json(pid, "transcript.json")
    c = load_json(pid, "clips.json")
    s = load_json(pid, "seo.json")
    return {
        "transcribed": t is not None,
        "segments": len((t or {}).get("segments", [])),
        "clips_found": len((c or {}).get("clips", [])),
        "packaged": s is not None,
    }


TOOLS: dict[str, Tool] = {
    "analyze": Tool("analyze", "Transcribe the video and detect silences.",
                    "{}", _t_analyze),
    "find_clips": Tool("find_clips", "Score moments and pick the best clips.",
                       "{}", _t_find_clips),
    "render_clip": Tool("render_clip", "Render one clip as 9:16 with burned captions.",
                       '{"clip_index": 0}', _t_render_clip),
    "export_clip": Tool("export_clip", "Export one clip for a platform.",
                       '{"clip_index": 0, "platform": "tiktok|youtube|square"}',
                       _t_export_clip),
    "make_montage": Tool("make_montage", "Stitch clips into one highlight reel.",
                        '{"clip_indices": [0,1,2], "platform": "tiktok"}',
                        _t_montage),
    "voiceover": Tool("voiceover", "Generate an AI voiceover from text.",
                     '{"text": "...", "speaker": "Ryan"}', _t_voiceover),
    "packaging": Tool("packaging", "Generate keywords, titles, descriptions.",
                     "{}", _t_packaging),
    "autopilot": Tool("autopilot", "Self-edit the full long video: cut silences/fillers, captions.",
                      '{"remove_silence": true, "remove_fillers": false, "captions": true}',
                      _t_autopilot),
    "project_status": Tool("project_status", "Summarize what is done so far.",
                          "{}", _t_status),
}
