"""Persistência do estado de um job de reunião.

Preparação para produção: SQLite (via SQLAlchemy) em vez do dict em memória
que existia até aqui — reiniciar o servidor não pode mais apagar jobs em
andamento. A interface pública (create/get/update_status/stage_durations,
o dataclass JobRecord devolvido por create/get) é a mesma que a versão em
memória expunha — os consumidores (PipelineFacade, app/api/jobs.py) não
precisam mudar. Ver docs/BACKEND_ARCHITECTURE.md.

Schema (criado automaticamente no primeiro uso, sem migração — não há dados
de produção reais a migrar, job_repository é efêmero por natureza):

    jobs               — um registro por job (estado atual). `attempts`
                         conta quantas vezes o job foi encontrado órfão no
                         boot do worker (ver requeue_orfaos) — proteção
                         contra "job veneno" que derruba o worker sempre
                         que é processado; não conta tentativas normais.
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

# Estágios não-terminais do pipeline (exceto QUEUED) — usado por
# requeue_orfaos() para achar jobs deixados a meio por uma instância
# anterior do worker que morreu.
_ESTAGIOS_EM_ANDAMENTO = [
    JobStatusValue.TRANSCRIBING,
    JobStatusValue.DIARIZING,
    JobStatusValue.IDENTIFYING,
    JobStatusValue.SUMMARIZING,
    JobStatusValue.EXTRACTING,
]


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
    attempts = Column(Integer, nullable=False, default=0)
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
    attempts: int = 0
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

    def next_queued(self) -> Optional[str]:
        """Job_id mais antigo (por created_at) ainda em `queued`, ou None se
        a fila estiver vazia. Assume um único worker dedicado consumindo a
        fila por vez (pressuposto do desenho: pipeline GPU-bound, ver
        docs/BACKEND_ARCHITECTURE.md) — não faz claim atômico contra outros
        consumidores concorrentes; quem tira o job de `queued` de fato é
        `pipeline_facade.executar()`, ao chamar update_status(TRANSCRIBING)
        como primeira ação."""
        with self._session_factory() as session:
            return session.scalars(
                select(JobRow.job_id)
                .where(JobRow.status == JobStatusValue.QUEUED.value)
                .order_by(JobRow.created_at)
                .limit(1)
            ).first()

    def requeue_orfaos(self, max_attempts: int) -> List[str]:
        """Chamado no boot do worker: todo job num estágio não-terminal
        (exceto `queued`) só pode ter sido deixado por uma instância
        anterior do worker que morreu no meio do processamento (mesmo
        pressuposto de next_queued() — um único worker por vez). Reprocessar
        do zero é seguro (pipeline_facade não faz checkpoint parcial, só
        persiste resultado ao chegar em DONE), então o padrão é reenfileirar
        (volta a `queued`, `attempts` += 1).

        Proteção contra "job veneno": se `attempts` já teria excedido
        `max_attempts`, não reenfileira de novo — marca `error` direto, para
        um job que sistematicamente derruba o worker não travar a fila para
        sempre. Retorna os job_ids afetados (reenfileirados ou marcados
        error)."""
        agora = datetime.now(timezone.utc)
        afetados: List[str] = []
        with self._lock, self._session_factory() as session:
            rows = session.scalars(
                select(JobRow).where(
                    JobRow.status.in_([s.value for s in _ESTAGIOS_EM_ANDAMENTO])
                )
            ).all()
            for row in rows:
                estagio_anterior = row.status
                row.attempts += 1
                if row.attempts > max_attempts:
                    row.status = JobStatusValue.ERROR.value
                    row.error_code = "WORKER_MAX_TENTATIVAS_EXCEDIDO"
                    row.error_message = (
                        f"Excedeu {max_attempts} tentativa(s) após crashes do worker "
                        f"(último estágio alcançado antes do crash: {estagio_anterior})."
                    )
                else:
                    row.status = JobStatusValue.QUEUED.value
                row.updated_at = agora
                session.add(JobStatusEventRow(job_id=row.job_id, status=row.status, occurred_at=agora))
                afetados.append(row.job_id)
            session.commit()
        return afetados

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
            attempts=row.attempts,
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
