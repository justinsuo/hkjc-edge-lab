"""Tiny in-process background job runner for slow actions (validate, fetch).

Single worker thread + dict registry — this is a local single-user app, so no Celery/Redis.
Jobs are serialized so a fetch and a validate can't race on the DB.
"""
from __future__ import annotations

import queue
import threading
import traceback
import uuid
from datetime import datetime, timezone


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class JobManager:
    def __init__(self):
        self._jobs: dict[str, dict] = {}
        self._q: "queue.Queue[tuple[str, callable]]" = queue.Queue()
        self._lock = threading.Lock()
        self._worker = threading.Thread(target=self._run, daemon=True)
        self._worker.start()

    def submit(self, job_type: str, fn) -> str:
        job_id = uuid.uuid4().hex[:12]
        with self._lock:
            self._jobs[job_id] = {"job_id": job_id, "type": job_type, "state": "queued",
                                  "progress": 0.0, "message": "queued", "result": None,
                                  "error": None, "created_at": _now(), "updated_at": _now()}
        self._q.put((job_id, fn))
        return job_id

    def get(self, job_id: str) -> dict | None:
        with self._lock:
            return self._jobs.get(job_id)

    def list(self) -> list[dict]:
        with self._lock:
            return sorted(self._jobs.values(), key=lambda j: j["created_at"], reverse=True)[:20]

    def _set(self, job_id: str, **kw):
        with self._lock:
            self._jobs[job_id].update(kw, updated_at=_now())

    def _run(self):
        while True:
            job_id, fn = self._q.get()
            self._set(job_id, state="running", message="running", progress=0.1)
            try:
                result = fn(lambda p, m="": self._set(job_id, progress=p, message=m))
                self._set(job_id, state="done", progress=1.0, message="done", result=result)
            except Exception as e:  # noqa: BLE001
                self._set(job_id, state="error", message=str(e),
                          error={"message": str(e), "trace": traceback.format_exc()[-1500:]})
            finally:
                self._q.task_done()
