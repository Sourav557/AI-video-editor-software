"""Worker: batch_export — Slice 18.

ONE job renders a batch of codec variants from the current timeline:
  1. the EDL renders ONCE to the mezzanine (edit.mp4) via the normal
     render_edl path (called directly via absolute import — the queue is
     single-threaded, so no queue-and-wait inside a worker);
  2. each batch item reuses the single-export transcode path
     (app.workers.codecs.transcode) sequentially.
Per-item status is published on job.note ({"item","of","codec","file",
"state"}) so the UI can show it while the job runs; progress goes through
the normal report() mechanism.
"""
from __future__ import annotations

import json
import os
import shutil

from ..projects import project_dir
from . import codecs as _codecs
from .render_edl import _unique_export_name

MAX_ITEMS = 8


class _JobShim:
    """Minimal stand-in for the orchestrator Job: render_edl.run only
    touches .project_id and .params."""

    def __init__(self, project_id: str, params: dict):
        self.project_id = project_id
        self.params = params


def run(job, report) -> dict:
    params = job.params or {}
    pid = job.project_id
    blocks = params.get("blocks") or []
    items = params.get("items") or []
    if not blocks:
        raise RuntimeError("empty timeline — nothing to render")
    if not items:
        raise RuntimeError("batch is empty — nothing to export")
    if len(items) > MAX_ITEMS:
        raise RuntimeError(f"batch too large (max {MAX_ITEMS} items)")

    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        raise RuntimeError("ffmpeg not found on PATH")

    # Sanitize + fail fast: a bad codec or a missing encoder aborts BEFORE
    # the (expensive) EDL render, never mid-batch.
    specs: list[dict] = []
    for it in items:
        if not isinstance(it, dict):
            raise RuntimeError("each batch item must be {codec, crf?, preset?}")
        try:
            spec = _codecs.clean_export_spec(
                it.get("codec", "h264"), it.get("crf"),
                it.get("preset"), it.get("profile"))
        except ValueError as e:
            raise RuntimeError(str(e))
        _codecs.assert_available(ffmpeg, spec["codec"])
        specs.append(spec)

    # 1) Render the EDL once -> mezzanine (the plain h264 path, no codec
    # options passed, so render_edl behaves exactly as it always did).
    from app.workers import render_edl
    render_edl.run(
        _JobShim(pid, {"blocks": blocks,
                       "captions": params.get("captions", True),
                       "titles": params.get("titles") or []}),
        lambda p: report(0.6 * max(0.0, min(1.0, p))))
    mez = project_dir(pid) / "edit.mp4"
    if not mez.exists():
        raise RuntimeError("mezzanine render produced no edit.mp4")

    # 2) Transcode per item, sequentially.
    n = len(specs)
    results: list[dict] = []
    for i, spec in enumerate(specs):
        name = _unique_export_name(pid, spec["file"])
        note = {"item": i + 1, "of": n, "codec": spec["codec"],
                "file": name, "state": "transcoding"}
        job.note = json.dumps(note)
        try:
            _codecs.transcode(ffmpeg, mez, project_dir(pid) / name, spec)
        except Exception:
            job.note = json.dumps({**note, "state": "failed"})
            raise
        results.append({"file": name, "codec": spec["codec"],
                        "size": os.path.getsize(project_dir(pid) / name),
                        "crf": spec["crf"], "preset": spec["preset"]})
        job.note = json.dumps({**note, "state": "done"})
        report(0.6 + 0.4 * (i + 1) / n)

    job.note = ""
    report(1.0)
    return {"mezzanine": "edit.mp4", "count": n, "items": results}
