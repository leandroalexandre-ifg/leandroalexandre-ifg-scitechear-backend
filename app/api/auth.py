from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi import status as http_status

from app.api.dependencies import get_current_user_id
from app.models.user import LoginRequest, LogoutRequest, RefreshRequest, TokenPair, UserPublic, UserRegisterRequest
from app.repositories.user_repository import get_user_repository
from app.services.auth_service import (
    AuthService,
    CredenciaisInvalidasError,
    DominioNaoPermitidoError,
    EmailJaCadastradoError,
    RateLimitedError,
    TokenInvalidoError,
)

router = APIRouter(prefix="/auth", tags=["auth"])


def _auth_service() -> AuthService:
    return AuthService(get_user_repository())


@router.post("/register", response_model=UserPublic, status_code=http_status.HTTP_201_CREATED)
async def register(payload: UserRegisterRequest, request: Request) -> UserPublic:
    try:
        return _auth_service().register(
            email=payload.email, password=payload.password, name=payload.name, ip=_client_ip(request)
        )
    except DominioNaoPermitidoError as exc:
        raise HTTPException(status_code=http_status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc
    except EmailJaCadastradoError as exc:
        raise HTTPException(status_code=http_status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    except RateLimitedError as exc:
        raise _rate_limit_response(exc) from exc


@router.post("/login", response_model=TokenPair)
async def login(payload: LoginRequest, request: Request) -> TokenPair:
    try:
        return _auth_service().login(email=payload.email, password=payload.password, ip=_client_ip(request))
    except CredenciaisInvalidasError as exc:
        raise HTTPException(status_code=http_status.HTTP_401_UNAUTHORIZED, detail=str(exc)) from exc
    except RateLimitedError as exc:
        raise _rate_limit_response(exc) from exc


@router.post("/refresh", response_model=TokenPair)
async def refresh(payload: RefreshRequest) -> TokenPair:
    try:
        return _auth_service().refresh(payload.refresh_token)
    except TokenInvalidoError as exc:
        raise HTTPException(status_code=http_status.HTTP_401_UNAUTHORIZED, detail=str(exc)) from exc


@router.post("/logout", status_code=http_status.HTTP_204_NO_CONTENT)
async def logout(payload: LogoutRequest) -> None:
    _auth_service().logout(payload.refresh_token)


@router.get("/me", response_model=UserPublic)
async def me(user_id: str = Depends(get_current_user_id)) -> UserPublic:
    try:
        return _auth_service().get_current_user(user_id)
    except TokenInvalidoError as exc:
        raise HTTPException(status_code=http_status.HTTP_401_UNAUTHORIZED, detail=str(exc)) from exc


def _client_ip(request: Request) -> str:
    # Sem proxy reverso confiável configurado ainda (dev/V1) — usar
    # request.client.host direto. Revisar para X-Forwarded-For quando a
    # topologia de deploy (nginx/load balancer) for definida.
    return request.client.host if request.client else ""


def _rate_limit_response(exc: RateLimitedError) -> HTTPException:
    return HTTPException(
        status_code=http_status.HTTP_429_TOO_MANY_REQUESTS,
        detail="Muitas tentativas. Tente novamente mais tarde.",
        headers={"Retry-After": str(exc.retry_after_seconds)},
    )
