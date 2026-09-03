"""Persistência de usuários, refresh tokens e tentativas de autenticação
falhas (rate limiting). Mesmo SQLite de job_repository.py (mesma
DATABASE_URL) — Base própria, self-contained, mesmo padrão: schema criado
automaticamente no primeiro uso, sem migração (nenhum dado de produção real
a migrar). Ver docs/BACKEND_ARCHITECTURE.md.

Schema:

    users                — uma linha por conta. Chave real de tudo que passa
                           a ser escopado por usuário (jobs, VoiceRepository).
    refresh_tokens       — um registro por refresh token emitido, indexado
                           por `jti` (claim do JWT). Diferente do access
                           token (stateless, só validado pela assinatura),
                           o refresh token precisa ser rastreado para que
                           POST /auth/logout tenha efeito real (revogação) —
                           sem isso, "sair da conta" seria decorativo.
    auth_failed_attempts — uma linha por tentativa falha de login/registro
                           (rate limiting simples, sem infraestrutura nova —
                           ver auth_service.py). Linhas fora da janela de
                           contagem são descartadas de forma oportunista a
                           cada escrita, para a tabela não crescer sem limite.
"""
import threading
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Optional

from sqlalchemy import Column, DateTime, Integer, String, create_engine, event, select
from sqlalchemy.engine import Engine, make_url
from sqlalchemy.orm import DeclarativeBase, sessionmaker


class Base(DeclarativeBase):
    pass


class UserRow(Base):
    __tablename__ = "users"

    id = Column(String, primary_key=True)
    email = Column(String, nullable=False, unique=True, index=True)
    name = Column(String, nullable=True)
    password_hash = Column(String, nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False)
    updated_at = Column(DateTime(timezone=True), nullable=False)


class RefreshTokenRow(Base):
    __tablename__ = "refresh_tokens"

    jti = Column(String, primary_key=True)
    user_id = Column(String, nullable=False, index=True)
    expires_at = Column(DateTime(timezone=True), nullable=False)
    revoked_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False)


class AuthFailedAttemptRow(Base):
    __tablename__ = "auth_failed_attempts"

    id = Column(Integer, primary_key=True, autoincrement=True)
    # "login" (identifier = e-mail) ou "register" (identifier = IP) — ver
    # app/services/auth_service.py.
    scope = Column(String, nullable=False, index=True)
    identifier = Column(String, nullable=False, index=True)
    occurred_at = Column(DateTime(timezone=True), nullable=False)


@dataclass
class UserRecord:
    id: str
    email: str
    name: Optional[str]
    password_hash: str
    created_at: datetime
    updated_at: datetime


def _as_utc(value: datetime) -> datetime:
    """SQLite não preserva tzinfo — todo timestamp gravado por este módulo já
    é UTC, então basta reanexar o tzinfo perdido na volta (mesmo padrão de
    job_repository._as_utc)."""
    return value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)


def _criar_engine(database_url: str) -> Engine:
    url = make_url(database_url)
    is_sqlite = url.get_backend_name() == "sqlite"

    connect_args = {"check_same_thread": False} if is_sqlite else {}
    engine = create_engine(database_url, future=True, connect_args=connect_args)

    if is_sqlite and url.database and url.database != ":memory:":
        from pathlib import Path

        Path(url.database).parent.mkdir(parents=True, exist_ok=True)

        @event.listens_for(engine, "connect")
        def _habilitar_wal(dbapi_connection, _):
            dbapi_connection.execute("PRAGMA journal_mode=WAL")

    return engine


class UserRepository:
    def __init__(self, database_url: str):
        self._engine = _criar_engine(database_url)
        Base.metadata.create_all(self._engine)
        self._session_factory = sessionmaker(bind=self._engine, future=True, expire_on_commit=False)
        self._lock = threading.Lock()

    # -- usuários -----------------------------------------------------

    def create_user(self, email: str, password_hash: str, name: Optional[str] = None) -> UserRecord:
        agora = datetime.now(timezone.utc)
        row = UserRow(
            id=str(uuid.uuid4()),
            email=email,
            name=name,
            password_hash=password_hash,
            created_at=agora,
            updated_at=agora,
        )
        with self._lock, self._session_factory() as session:
            session.add(row)
            session.commit()
            session.refresh(row)
        return self._to_user_record(row)

    def get_user_by_email(self, email: str) -> Optional[UserRecord]:
        with self._session_factory() as session:
            row = session.scalars(select(UserRow).where(UserRow.email == email)).first()
        return self._to_user_record(row) if row else None

    def get_user_by_id(self, user_id: str) -> Optional[UserRecord]:
        with self._session_factory() as session:
            row = session.get(UserRow, user_id)
        return self._to_user_record(row) if row else None

    # -- refresh tokens -------------------------------------------------

    def create_refresh_token(self, jti: str, user_id: str, expires_at: datetime) -> None:
        with self._lock, self._session_factory() as session:
            session.add(
                RefreshTokenRow(
                    jti=jti,
                    user_id=user_id,
                    expires_at=expires_at,
                    created_at=datetime.now(timezone.utc),
                )
            )
            session.commit()

    def get_refresh_token(self, jti: str) -> Optional[RefreshTokenRow]:
        with self._session_factory() as session:
            row = session.get(RefreshTokenRow, jti)
            if row is None:
                return None
            session.expunge(row)
        return row

    def revoke_refresh_token(self, jti: str) -> None:
        with self._lock, self._session_factory() as session:
            row = session.get(RefreshTokenRow, jti)
            if row is None or row.revoked_at is not None:
                return
            row.revoked_at = datetime.now(timezone.utc)
            session.commit()

    # -- rate limiting ----------------------------------------------------

    def record_failed_attempt(self, scope: str, identifier: str, retention: timedelta) -> None:
        agora = datetime.now(timezone.utc)
        with self._lock, self._session_factory() as session:
            session.add(AuthFailedAttemptRow(scope=scope, identifier=identifier, occurred_at=agora))
            # Limpeza oportunista: descarta linhas fora da janela de retenção
            # a cada escrita, em vez de um job de limpeza separado — evita
            # crescimento ilimitado sem exigir infraestrutura nova.
            limite = agora - retention
            session.query(AuthFailedAttemptRow).filter(AuthFailedAttemptRow.occurred_at < limite).delete()
            session.commit()

    def count_recent_failed_attempts(self, scope: str, identifier: str, window: timedelta) -> int:
        limite = datetime.now(timezone.utc) - window
        with self._session_factory() as session:
            return (
                session.query(AuthFailedAttemptRow)
                .filter(
                    AuthFailedAttemptRow.scope == scope,
                    AuthFailedAttemptRow.identifier == identifier,
                    AuthFailedAttemptRow.occurred_at >= limite,
                )
                .count()
            )

    def clear_failed_attempts(self, scope: str, identifier: str) -> None:
        with self._lock, self._session_factory() as session:
            session.query(AuthFailedAttemptRow).filter(
                AuthFailedAttemptRow.scope == scope, AuthFailedAttemptRow.identifier == identifier
            ).delete()
            session.commit()

    def _to_user_record(self, row: UserRow) -> UserRecord:
        return UserRecord(
            id=row.id,
            email=row.email,
            name=row.name,
            password_hash=row.password_hash,
            created_at=_as_utc(row.created_at),
            updated_at=_as_utc(row.updated_at),
        )


_user_repository_singleton: Optional[UserRepository] = None


def get_user_repository() -> UserRepository:
    from app.config import get_settings

    global _user_repository_singleton
    if _user_repository_singleton is None:
        _user_repository_singleton = UserRepository(get_settings().database_url_efetivo)
    return _user_repository_singleton


def reset_user_repository() -> None:
    """Descarta o singleton — usado nos testes para isolar cada teste com seu
    próprio STORAGE_ROOT/DATABASE_URL (mesmo padrão de
    job_repository.reset_job_repository)."""
    global _user_repository_singleton
    _user_repository_singleton = None
