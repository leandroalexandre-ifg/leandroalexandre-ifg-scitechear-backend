"""Autenticação: hashing de senha (Argon2id), emissão/validação de JWT
(access + refresh), e rate limiting simples de /auth/login e /auth/register.
Ver docs/BACKEND_ARCHITECTURE.md para o raciocínio completo por trás das
escolhas (por que Argon2id em vez de passlib, por que refresh token
rastreado em banco em vez de 100% stateless, por que rate limit por e-mail
no login e por IP no registro).
"""
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Optional

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError

from app.config import Settings, get_settings
from app.models.user import TokenPair, UserPublic
from app.repositories.user_repository import UserRepository

_hasher = PasswordHasher()


class AuthError(Exception):
    """Base de todos os erros de autenticação — app/api/auth.py mapeia cada
    subclasse para o código HTTP correspondente."""


class EmailJaCadastradoError(AuthError):
    pass


class CredenciaisInvalidasError(AuthError):
    pass


class TokenInvalidoError(AuthError):
    pass


class RateLimitedError(AuthError):
    def __init__(self, retry_after_seconds: int):
        self.retry_after_seconds = retry_after_seconds
        super().__init__(f"Muitas tentativas — tente novamente em {retry_after_seconds}s.")


@dataclass
class _RefreshClaims:
    user_id: str
    jti: str


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verificar_senha(password: str, password_hash: str) -> bool:
    try:
        return _hasher.verify(password_hash, password)
    except VerifyMismatchError:
        return False


def _jwt_secret(settings: Settings) -> str:
    if not settings.jwt_secret_key:
        raise RuntimeError(
            "JWT_SECRET_KEY não configurado — obrigatório para emitir ou validar tokens. "
            "Gerar em produção com `openssl rand -hex 32`."
        )
    return settings.jwt_secret_key


def _criar_access_token(user_id: str, settings: Settings) -> str:
    agora = datetime.now(timezone.utc)
    payload = {
        "sub": user_id,
        "type": "access",
        # jti só para unicidade do token (dois tokens emitidos no mesmo
        # segundo, com o mesmo iat/exp, seriam byte-idênticos sem isso) —
        # não é rastreado em banco como o do refresh token, access token
        # continua stateless.
        "jti": str(uuid.uuid4()),
        "iat": agora,
        "exp": agora + timedelta(minutes=settings.jwt_access_token_expire_minutes),
    }
    return jwt.encode(payload, _jwt_secret(settings), algorithm=settings.jwt_algorithm)


def decode_access_token(token: str, settings: Optional[Settings] = None) -> str:
    """Devolve o user_id (claim 'sub'). Levanta TokenInvalidoError para
    qualquer token ausente, malformado, expirado ou de tipo errado (ex.: um
    refresh token usado como access token)."""
    settings = settings or get_settings()
    try:
        payload = jwt.decode(token, _jwt_secret(settings), algorithms=[settings.jwt_algorithm])
    except jwt.PyJWTError as exc:
        raise TokenInvalidoError("Token de acesso inválido ou expirado.") from exc

    if payload.get("type") != "access":
        raise TokenInvalidoError("Token não é um access token.")
    return payload["sub"]


class AuthService:
    def __init__(self, repository: UserRepository, settings: Optional[Settings] = None):
        self._repo = repository
        self._settings = settings or get_settings()

    # -- registro / login ------------------------------------------------

    def register(self, email: str, password: str, name: Optional[str] = None, ip: str = "") -> UserPublic:
        self._checar_rate_limit(
            scope="register",
            identifier=ip or "sem-ip",
            max_attempts=self._settings.auth_register_max_attempts,
            window=timedelta(minutes=self._settings.auth_register_window_minutes),
        )

        if self._repo.get_user_by_email(email) is not None:
            self._registrar_falha("register", ip or "sem-ip")
            raise EmailJaCadastradoError(f"E-mail {email} já cadastrado.")

        record = self._repo.create_user(email=email, password_hash=hash_password(password), name=name)
        return UserPublic(user_id=record.id, email=record.email, name=record.name)

    def login(self, email: str, password: str, ip: str = "") -> TokenPair:
        self._checar_rate_limit(
            scope="login",
            identifier=email,
            max_attempts=self._settings.auth_login_max_attempts,
            window=timedelta(minutes=self._settings.auth_login_window_minutes),
        )

        record = self._repo.get_user_by_email(email)
        if record is None or not verificar_senha(password, record.password_hash):
            self._registrar_falha("login", email)
            raise CredenciaisInvalidasError("E-mail ou senha inválidos.")

        self._repo.clear_failed_attempts("login", email)
        return self._emitir_par_de_tokens(record.id)

    def refresh(self, refresh_token: str) -> TokenPair:
        claims = self._decodificar_refresh_token(refresh_token)

        row = self._repo.get_refresh_token(claims.jti)
        if row is None or row.revoked_at is not None or _as_utc(row.expires_at) < datetime.now(timezone.utc):
            raise TokenInvalidoError("Refresh token inválido, expirado ou revogado.")

        # Rotação: o token usado é invalidado antes de emitir o próximo par —
        # mitigação padrão contra reuso de um refresh token vazado.
        self._repo.revoke_refresh_token(claims.jti)
        return self._emitir_par_de_tokens(claims.user_id)

    def logout(self, refresh_token: str) -> None:
        """Idempotente por design: revoga se o token for válido e existir; se
        não, não vaza informação sobre o motivo (token alheio, já revogado,
        nunca existiu) — sempre retorna sem erro."""
        try:
            claims = self._decodificar_refresh_token(refresh_token)
        except TokenInvalidoError:
            return
        self._repo.revoke_refresh_token(claims.jti)

    def get_current_user(self, user_id: str) -> UserPublic:
        record = self._repo.get_user_by_id(user_id)
        if record is None:
            raise TokenInvalidoError("Usuário do token não existe mais.")
        return UserPublic(user_id=record.id, email=record.email, name=record.name)

    # -- internos ----------------------------------------------------------

    def _emitir_par_de_tokens(self, user_id: str) -> TokenPair:
        settings = self._settings
        access_token = _criar_access_token(user_id, settings)

        jti = str(uuid.uuid4())
        agora = datetime.now(timezone.utc)
        expires_at = agora + timedelta(days=settings.jwt_refresh_token_expire_days)
        refresh_payload = {
            "sub": user_id,
            "type": "refresh",
            "jti": jti,
            "iat": agora,
            "exp": expires_at,
        }
        refresh_token = jwt.encode(refresh_payload, _jwt_secret(settings), algorithm=settings.jwt_algorithm)
        self._repo.create_refresh_token(jti=jti, user_id=user_id, expires_at=expires_at)

        return TokenPair(
            access_token=access_token,
            refresh_token=refresh_token,
            expires_in=settings.jwt_access_token_expire_minutes * 60,
        )

    def _decodificar_refresh_token(self, token: str) -> _RefreshClaims:
        try:
            payload = jwt.decode(token, _jwt_secret(self._settings), algorithms=[self._settings.jwt_algorithm])
        except jwt.PyJWTError as exc:
            raise TokenInvalidoError("Refresh token inválido ou expirado.") from exc

        if payload.get("type") != "refresh" or "jti" not in payload:
            raise TokenInvalidoError("Token não é um refresh token.")
        return _RefreshClaims(user_id=payload["sub"], jti=payload["jti"])

    def _checar_rate_limit(self, scope: str, identifier: str, max_attempts: int, window: timedelta) -> None:
        tentativas = self._repo.count_recent_failed_attempts(scope, identifier, window)
        if tentativas >= max_attempts:
            raise RateLimitedError(retry_after_seconds=int(window.total_seconds()))

    def _registrar_falha(self, scope: str, identifier: str) -> None:
        # Retenção da limpeza oportunista: a maior janela relevante entre
        # login e register, com folga — nunca menor que a janela usada para
        # decidir o bloqueio.
        retention = timedelta(
            minutes=max(self._settings.auth_login_window_minutes, self._settings.auth_register_window_minutes)
        )
        self._repo.record_failed_attempt(scope, identifier, retention=retention)


def _as_utc(value: datetime) -> datetime:
    return value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)
