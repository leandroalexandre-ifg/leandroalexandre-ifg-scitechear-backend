"""Persistência do estado de um job de reunião.

Fase 6: em memória (processo único), protegida por lock — substitui o dict
`_JOBS` que vivia em app/api/jobs.py desde a Fase 1. A interface (create/get/
update_status) é a mesma que um backend persistente (Redis/DB) usaria depois
ao introduzir fila real; trocar a implementação não deve exigir mudanças na
API nem no PipelineFacade.
"""
import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Dict, List, Optional

from app.models.job import JobError, JobStatusValue
from app.models.participant import Participant


@dataclass
class JobRecord:
    job_id: str
    title: Optional[str]
    participants: List[Participant]
    expected_speaker_count: Optional[int]
    status: JobStatusValue = JobStatusValue.QUEUED
    error: Optional[JobError] = None
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


class JobRepository:
    def __init__(self):
        self._jobs: Dict[str, JobRecord] = {}
        self._lock = threading.Lock()

    def create(
        self,
        job_id: str,
        title: Optional[str],
        participants: List[Participant],
        expected_speaker_count: Optional[int],
    ) -> JobRecord:
        record = JobRecord(
            job_id=job_id,
            title=title,
            participants=participants,
            expected_speaker_count=expected_speaker_count,
        )
        with self._lock:
            self._jobs[job_id] = record
        return record

    def get(self, job_id: str) -> Optional[JobRecord]:
        with self._lock:
            return self._jobs.get(job_id)

    def update_status(
        self, job_id: str, status: JobStatusValue, error: Optional[JobError] = None
    ) -> None:
        with self._lock:
            record = self._jobs.get(job_id)
            if record is None:
                return
            record.status = status
            record.error = error
            record.updated_at = datetime.now(timezone.utc)


_job_repository_singleton: Optional[JobRepository] = None


def get_job_repository() -> JobRepository:
    """Instância compartilhada entre requisições — o estado do job precisa
    sobreviver entre o POST /upload e os GET /status, /resultado."""
    global _job_repository_singleton
    if _job_repository_singleton is None:
        _job_repository_singleton = JobRepository()
    return _job_repository_singleton
