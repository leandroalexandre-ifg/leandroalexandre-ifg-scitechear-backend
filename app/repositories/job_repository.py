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
from typing import Dict, List, Optional, Tuple

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
    # Histórico de transições (status, timestamp de quando ENTROU nesse
    # status) — usado só para medir tempo por estágio (instrumentação de
    # performance, ver docs/PENDENCIAS.md). Não faz parte do contrato HTTP
    # (JobStatusResponse continua só com o status atual).
    status_history: List[Tuple[JobStatusValue, datetime]] = field(default_factory=list)


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
        record.status_history.append((record.status, record.created_at))
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
            record.status_history.append((status, record.updated_at))

    def stage_durations(self, job_id: str) -> Dict[str, float]:
        """Segundos gastos em cada estágio, calculado a partir do próprio
        `status_history` de transições já registrado — não uma medição
        paralela. Chave é o estágio que estava ATIVO durante aquele
        intervalo (ex.: "transcribing" = tempo entre entrar em TRANSCRIBING
        e entrar no próximo status). O último estágio (DONE/ERROR) não tem
        duração — é terminal, não um trabalho em si."""
        with self._lock:
            record = self._jobs.get(job_id)
            if record is None or len(record.status_history) < 2:
                return {}
            historico = list(record.status_history)

        return {
            status.value: (proximo_ts - ts).total_seconds()
            for (status, ts), (_, proximo_ts) in zip(historico, historico[1:])
        }


_job_repository_singleton: Optional[JobRepository] = None


def get_job_repository() -> JobRepository:
    """Instância compartilhada entre requisições — o estado do job precisa
    sobreviver entre o POST /upload e os GET /status, /resultado."""
    global _job_repository_singleton
    if _job_repository_singleton is None:
        _job_repository_singleton = JobRepository()
    return _job_repository_singleton
