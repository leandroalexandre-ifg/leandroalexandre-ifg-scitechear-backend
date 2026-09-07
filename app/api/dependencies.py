import logging
from typing import Optional

from fastapi import HTTPException, Request
from fastapi import status as http_status

from app.services.auth_service import TokenInvalidoError, decode_access_token

logger = logging.getLogger(__name__)


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
        _log_401(request, "cabeçalho Authorization ausente ou sem o prefixo 'Bearer '")
        raise HTTPException(
            status_code=http_status.HTTP_401_UNAUTHORIZED, detail="Token de acesso ausente."
        )
    try:
        return decode_access_token(token)
    except TokenInvalidoError as exc:
        _log_401(request, str(exc))
        raise HTTPException(status_code=http_status.HTTP_401_UNAUTHORIZED, detail=str(exc)) from exc


def _log_401(request: Request, motivo: str) -> None:
    """Registra POR QUE a requisição foi recusada. Pedido do frontend para o
    teste conjunto de 07/09/2026: os dois casos já se distinguiam no corpo da
    resposta (`detail`), mas do lado do servidor "token ausente" (app não
    mandou nada) e "token inválido ou expirado" (app mandou algo que não
    serve) produziam o mesmo silêncio — e são bugs diferentes de investigar.

    INFO, não WARNING: um access token expirando é o curso normal da vida de
    uma sessão, não um incidente. E loga `url.path`, nunca `url` inteira: a
    query string é onde o WebSocket carrega o token (ver
    RedigirTokenDeQueryString em app/main.py), e credencial não vai para o
    journal."""
    logger.info("401 em %s %s: %s.", request.method, request.url.path, motivo)


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
