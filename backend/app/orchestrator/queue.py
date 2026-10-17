"""Orchestrator: boring, reliable scheduling. NOT an LLM — just a job DAG + queue.

- Workers register by kind and declare nothing but a run(job, report) function.
- Jobs declare dependencies; the orchestrator topologically unblocks them.
- Independent jobs (e.g. transcribe + silence) run back-to-back without blocking
  each other; priorities let interactive jobs preempt batch work.
- Jobs must be idempotent: running twice never corrupts state.
"""
from __future__ import annotations

import threading
import time
import uuid
from dataclasses import dataclass, field
from typing import Callable

QUEUED, RUNNING, DONE, FAILED = "queued", "running", "done", "failed"


@dataclass
class Job:
    kind: str
    project_id: str
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    depends_on: list = field(default_factory=list)
    priority: int = 0
    params: dict = field(default_factory=dict)
    status: str = QUEUED
    progress: float = 0.0
    result: dict | None = None
    error: str | None = None
    created_at: float = field(default_factory=time.time)
    started_at: float | None = None
    finished_at: float | None = None


class Orchestrator:
    def __init__(self):
        self.jobs: dict[str, Job] = {}
        self.lock = threading.Lock()
        self._workers: dict[str, Callable] = {}

    def register(self, kind: str, fn: Callable):
        """Register a worker: fn(job, report_progress_0_to_1) -> dict result."""
        self._workers[kind] = fn

    def submit(self, kind: str, project_id: str, depends_on=(), priority: int = 0,
               params: dict | None = None) -> Job:
        job = Job(kind=kind, project_id=project_id,
                  depends_on=list(depends_on), priority=priority,
                  params=params or {})
        with self.lock:
            self.jobs[job.id] = job
        return job

    def get(self, job_id: str) -> Job | None:
        with self.lock:
            return self.jobs.get(job_id)

    def for_project(self, project_id: str) -> list[Job]:
        with self.lock:
            return [j for j in self.jobs.values() if j.project_id == project_id]

    def _ready(self) -> list[Job]:
        with self.lock:
            jobs = list(self.jobs.values())
        ready = []
        for j in jobs:
            if j.status != QUEUED:
                continue
            deps = [self.jobs[d] for d in j.depends_on if d in self.jobs]
            if any(d.status == FAILED for d in deps):
                j.status, j.error = FAILED, "a dependency failed"
            elif all(d.status == DONE for d in deps):
                ready.append(j)
        return sorted(ready, key=lambda j: (-j.priority, j.created_at))

    def run_forever(self):
        while True:
            ready = self._ready()
            if not ready:
                time.sleep(0.25)
                continue
            job = ready[0]
            job.status, job.started_at = RUNNING, time.time()
            try:
                fn = self._workers[job.kind]
                job.result = fn(job, lambda p: setattr(job, "progress", max(0.0, min(1.0, p))))
                job.status, job.progress = DONE, 1.0
            except Exception as e:  # worker crash never kills the queue
                job.status, job.error = FAILED, f"{type(e).__name__}: {e}"
            finally:
                job.finished_at = time.time()


orchestrator = Orchestrator()
