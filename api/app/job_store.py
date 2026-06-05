from __future__ import annotations

from datetime import datetime
from pathlib import Path
from threading import Lock
from typing import Callable
from uuid import uuid4

from .models import DEFAULT_MODELS, JobInternal, JobPublic, JobStatus, ProviderName, now_utc


class JobStore:
    def __init__(self, data_dir: Path) -> None:
        self.data_dir = data_dir
        self.jobs_dir = data_dir / "jobs"
        self.jobs_dir.mkdir(parents=True, exist_ok=True)
        self._jobs: dict[str, JobInternal] = {}
        self._lock = Lock()

    def create(self, filename: str, provider: ProviderName, model: str | None) -> JobInternal:
        job_id = uuid4().hex
        job_dir = self.jobs_dir / job_id
        job_dir.mkdir(parents=True, exist_ok=True)
        safe_name = Path(filename).name or "paper.pdf"
        pdf_path = job_dir / "source.pdf"
        now = now_utc()
        job = JobInternal(
            id=job_id,
            filename=safe_name,
            provider=provider,
            model=model or DEFAULT_MODELS[provider],
            status=JobStatus.queued,
            progress=0,
            current_step="Queued",
            pages=0,
            created_at=now,
            updated_at=now,
            job_dir=job_dir,
            source_pdf=pdf_path,
        )
        with self._lock:
            self._jobs[job_id] = job
        return job

    def get(self, job_id: str) -> JobInternal | None:
        with self._lock:
            return self._jobs.get(job_id)

    def list_public(self) -> list[JobPublic]:
        with self._lock:
            return [job.public() for job in self._jobs.values()]

    def update(self, job_id: str, **changes: object) -> JobInternal:
        with self._lock:
            if job_id not in self._jobs:
                raise KeyError(job_id)
            job = self._jobs[job_id]
            for key, value in changes.items():
                setattr(job, key, value)
            job.updated_at = now_utc()
            self._jobs[job_id] = job
            return job

    def progress_updater(self, job_id: str) -> Callable[[int, str], None]:
        def update(progress: int, step: str) -> None:
            self.update(job_id, progress=max(0, min(100, progress)), current_step=step)

        return update
