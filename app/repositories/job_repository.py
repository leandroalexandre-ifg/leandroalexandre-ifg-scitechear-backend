"""Persistência do estado de um job de reunião.

Preparação para produção: SQLite (via SQLAlchemy) em vez do dict em memória
que existia até aqui — reiniciar o servidor não pode mais apagar jobs em
andamento. A interface pública (create/get/update_status/stage_durations,
o dataclass JobRecord devolvido por create/get) é a mesma que a versão em
memória expunha — os consumidores (PipelineFacade, app/api/jobs.py) não
precisam mudar. Ver docs/BACKEND_ARCHITECTURE.md.

Schema (criado automaticamente no primeiro uso, sem migração — não há dados
de produção reais a migrar, job_repository é efêmero por natureza):

    jobs               — um registro por job (estado atual).
    job_status_events  — uma linha por transição de status (INSERT-only);
                         só alimenta stage_durations() (instrumentação de
                         performance), não faz parte do contrato HTTP.
"""
import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from sqlalchemy import JSON, Column, DateTime, ForeignKey, Integer, String, create_engine, event, select
from sqlalchemy.engine import Engine, make_url
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.config import get_settings
from app.models.job import JobError, JobStatusValue
from app.models.participant import Participant


class Base(DeclarativeBase):
    pass


class JobRow(Base):
    __tablename__ = "jobs"

    job_id = Column(String, primary_key=True)
    title = Column(String, nullable=True)
    participants = Column(JSON, nullable=False)
    expected_speaker_count = Column(Integer, nullable=True)
    status = Column(String, nullable=False)
    error_code = Column(String, nullable=True)
    error_message = Column(String, nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False)
    updated_at = Column(DateTime(timezone=True), nullable=False)


class JobStatusEventRow(Base):
    __tablename__ = "job_status_events"

    id = Column(Integer, primary_key=True, autoincrement=True)
    job_id = Column(String, ForeignKey("jobs.job_id"), nullable=False)
    status = Column(String, nullable=False)
    occurred_at = Column(DateTime(timezone=True), nullable=False)


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


def _as_utc(value: datetime) -> datetime:
    """SQLite não preserva tzinfo — todo timestamp gravado por este módulo
    já é UTC, então basta reanexar o tzinfo perdido na volta."""
    return value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)


def _criar_engine(database_url: str) -> Engine:
    url = make_url(database_url)
    is_sqlite = url.get_backend_name() == "sqlite"

    connect_args = {"check_same_thread": False} if is_sqlite else {}
    engine = create_engine(database_url, future=True, connect_args=connect_args)

    if is_sqlite and url.database and url.database != ":memory:":
        Path(url.database).parent.mkdir(parents=True, exist_ok=True)

        @event.listens_for(engine, "connect")
        def _habilitar_wal(dbapi_connection, _):
            # WAL: leitores concorrentes não bloqueiam o escritor — suficiente
            # para o volume de escrita esperado (poucas transições por job),
            # inclusive com múltiplos workers futuros (item de fila real).
            dbapi_connection.execute("PRAGMA journal_mode=WAL")

    return engine


class JobRepository:
    def __init__(self, database_url: str):
        self._engine = _criar_engine(database_url)
        Base.metadata.create_all(self._engine)
        self._session_factory = sessionmaker(bind=self._engine, future=True, expire_on_commit=False)
        self._lock = threading.Lock()

    def create(
        self,
        job_id: str,
        title: Optional[str],
        participants: List[Participant],
        expected_speaker_count: Optional[int],
    ) -> JobRecord:
        agora = datetime.now(timezone.utc)
        row = JobRow(
            job_id=job_id,
            title=title,
            participants=[p.model_dump() for p in participants],
            expected_speaker_count=expected_speaker_count,
            status=JobStatusValue.QUEUED.value,
            created_at=agora,
            updated_at=agora,
        )
        with self._lock, self._session_factory() as session:
            session.add(row)
            session.add(
                JobStatusEventRow(job_id=job_id, status=JobStatusValue.QUEUED.value, occurred_at=agora)
            )
            session.commit()

        return self._to_record(row, [(JobStatusValue.QUEUED, agora)])

    def get(self, job_id: str) -> Optional[JobRecord]:
        with self._session_factory() as session:
            row = session.get(JobRow, job_id)
            if row is None:
                return None
            historico = self._carregar_historico(session, job_id)
        return self._to_record(row, historico)

    def update_status(
        self, job_id: str, status: JobStatusValue, error: Optional[JobError] = None
    ) -> None:
        agora = datetime.now(timezone.utc)
        with self._lock, self._session_factory() as session:
            row = session.get(JobRow, job_id)
            if row is None:
                return
            row.status = status.value
            row.error_code = error.code if error else None
            row.error_message = error.message if error else None
            row.updated_at = agora
            session.add(JobStatusEventRow(job_id=job_id, status=status.value, occurred_at=agora))
            session.commit()

    def stage_durations(self, job_id: str) -> Dict[str, float]:
        """Segundos gastos em cada estágio, calculado a partir do próprio
        histórico de transições já registrado (`job_status_events`) — não
        uma medição paralela. Chave é o estágio que estava ATIVO durante
        aquele intervalo (ex.: "transcribing" = tempo entre entrar em
        TRANSCRIBING e entrar no próximo status). O último estágio (DONE/
        ERROR) não tem duração — é terminal, não um trabalho em si."""
        with self._session_factory() as session:
            historico = self._carregar_historico(session, job_id)
        if len(historico) < 2:
            return {}

        return {
            status.value: (proximo_ts - ts).total_seconds()
            for (status, ts), (_, proximo_ts) in zip(historico, historico[1:])
        }

    def _carregar_historico(self, session: Session, job_id: str) -> List[Tuple[JobStatusValue, datetime]]:
        rows = session.scalars(
            select(JobStatusEventRow)
            .where(JobStatusEventRow.job_id == job_id)
            .order_by(JobStatusEventRow.id)
        ).all()
        return [(JobStatusValue(r.status), _as_utc(r.occurred_at)) for r in rows]

    def _to_record(self, row: JobRow, historico: List[Tuple[JobStatusValue, datetime]]) -> JobRecord:
        error = JobError(code=row.error_code, message=row.error_message) if row.error_code else None
        return JobRecord(
            job_id=row.job_id,
            title=row.title,
            participants=[Participant(**p) for p in row.participants],
            expected_speaker_count=row.expected_speaker_count,
            status=JobStatusValue(row.status),
            error=error,
            created_at=_as_utc(row.created_at),
            updated_at=_as_utc(row.updated_at),
            status_history=historico,
        )


_job_repository_singleton: Optional[JobRepository] = None


def get_job_repository() -> JobRepository:
    """Instância compartilhada entre requisições — o estado do job precisa
    sobreviver entre o POST /upload e os GET /status, /resultado (e agora
    também a um restart do processo, ver DATABASE_URL em app/config.py)."""
    global _job_repository_singleton
    if _job_repository_singleton is None:
        _job_repository_singleton = JobRepository(get_settings().database_url_efetivo)
    return _job_repository_singleton


def reset_job_repository() -> None:
    """Descarta o singleton — usado nos testes para isolar cada teste com seu
    próprio STORAGE_ROOT/DATABASE_URL (ver tests/conftest.py). Não tem uso em
    runtime normal."""
    global _job_repository_singleton
    _job_repository_singleton = None
