from typing import Optional

from fastapi import HTTPException, Request
from fastapi import status as http_status

from app.services.auth_service import TokenInvalidoError, decode_access_token


def _extrair_token_do_header(request: Request) -> Optional[str]:
    header = request.headers.get("Authorization", "")
    if not header.startswith("Bearer "):
        return None
    return header[len("Bearer "):]


def get_current_user_id(request: Request) -> str:
    """Dependency FastAPI usada por todas as rotas protegidas (jobs.py,
    participants.py). Só extrai e valida o access token — nenhuma lógica de
    autenticação além disso mora na camada HTTP (mesma filosofia de
    "API burra" do resto do projeto, ver docs/BACKEND_ARCHITECTURE.md §2)."""
    token = _extrair_token_do_header(request)
    if token is None:
        raise HTTPException(
            status_code=http_status.HTTP_401_UNAUTHORIZED, detail="Token de acesso ausente."
        )
    try:
        return decode_access_token(token)
    except TokenInvalidoError as exc:
        raise HTTPException(status_code=http_status.HTTP_401_UNAUTHORIZED, detail=str(exc)) from exc


def user_id_from_ws_token(token: Optional[str]) -> Optional[str]:
    """Usado por WS /ws/{job_id} — o handshake de WebSocket não permite
    header Authorization customizado em todo cliente, então o access token
    vem por query param (?token=). Devolve None em vez de levantar, para o
    handler fechar a conexão com um código específico (4401) em vez de um
    500."""
    if not token:
        return None
    try:
        return decode_access_token(token)
    except TokenInvalidoError:
        return None
