import asyncio
import contextlib
import json
import logging
import time
import uuid
from typing import List, Optional

from fastapi import (
    APIRouter,
    Depends,
    File,
    Form,
    HTTPException,
    Query,
    Response,
    UploadFile,
    WebSocket,
    WebSocketDisconnect,
)
from fastapi import status as http_status
from pydantic import TypeAdapter, ValidationError
from starlette.concurrency import run_in_threadpool

from app.api.dependencies import get_current_user_id, user_id_from_ws_token
from app.config import get_settings
from app.models.job import (
    JobStatusResponse,
    JobStatusValue,
    MeetingSummary,
    MeetingTitleUpdate,
    UploadResponse,
)
from app.models.participant import Participant
from app.models.result import MeetingResult
from app.repositories.job_repository import get_job_repository
from app.repositories.storage_repository import ArquivoGrandeDemaisError
from app.services.job_runner import result_repository, storage_repository

logger = logging.getLogger(__name__)

router = APIRouter(tags=["jobs"])

_PARTICIPANTS_ADAPTER = TypeAdapter(List[Participant])


def _validate_wav(file: UploadFile) -> None:
    filename = (file.filename or "").lower()
    content_type = (file.content_type or "").lower()
    is_wav_name = filename.endswith(".wav")
    is_wav_type = content_type in {"audio/wav", "audio/x-wav", "audio/wave", "audio/vnd.wave"}
    if not (is_wav_name or is_wav_type):
        raise HTTPException(
            status_code=http_status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="Arquivo de áudio deve ser WAV (16 kHz mono).",
        )


@router.post("/upload", response_model=UploadResponse, status_code=http_status.HTTP_202_ACCEPTED)
async def upload_meeting(
    file: UploadFile = File(...),
    title: Optional[str] = Form(None),
    participants: str = Form(...),
    expected_speaker_count: Optional[int] = Form(None),
    user_id: str = Depends(get_current_user_id),
) -> UploadResponse:
    _validate_wav(file)

    try:
        participants_data = json.loads(participants)
        parsed_participants = _PARTICIPANTS_ADAPTER.validate_python(participants_data)
    except (json.JSONDecodeError, ValidationError) as exc:
        raise HTTPException(
            status_code=http_status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=f"Campo 'participants' inválido: {exc}",
        ) from exc

    if expected_speaker_count is not None and expected_speaker_count < 1:
        raise HTTPException(
            status_code=http_status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="expected_speaker_count deve ser >= 1.",
        )

    job_id = str(uuid.uuid4())
    # Grava direto no disco, em pedaços, com o teto aplicado durante a
    # escrita. O job só é criado depois: upload recusado não deixa job órfão
    # na fila para o worker pegar.
    try:
        await run_in_threadpool(
            storage_repository().save_audio_stream,
            job_id,
            file.file,
            file.filename or "reuniao.wav",
            get_settings().max_upload_bytes,
        )
    except ArquivoGrandeDemaisError as exc:
        raise HTTPException(
            status_code=http_status.HTTP_413_CONTENT_TOO_LARGE,
            detail=f"Áudio excede o limite de {get_settings().max_upload_mb} MB.",
        ) from exc

    get_job_repository().create(
        job_id=job_id,
        user_id=user_id,
        title=title,
        participants=parsed_participants,
        expected_speaker_count=expected_speaker_count,
    )

    # Responde rápido; o processamento roda no worker dedicado (app/worker.py,
    # processo separado), que consome a fila (job_repository) de forma
    # assíncrona — /upload só grava o job, não dispara nada aqui. Ver
    # docs/BACKEND_ARCHITECTURE.md.
    return UploadResponse(job_id=job_id, status=JobStatusValue.QUEUED)


@router.get("/meetings", response_model=List[MeetingSummary])
async def list_meetings(
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    user_id: str = Depends(get_current_user_id),
) -> List[MeetingSummary]:
    records = get_job_repository().list_by_user(user_id, limit=limit, offset=offset)
    return [_meeting_summary(r) for r in records]


def _meeting_summary(record) -> MeetingSummary:
    return MeetingSummary(
        job_id=record.job_id,
        title=record.title,
        status=record.status,
        participants=record.participants,
        error=record.error,
        created_at=record.created_at,
        updated_at=record.updated_at,
    )


@router.patch("/meetings/{job_id}", response_model=MeetingSummary)
async def rename_meeting(
    job_id: str, payload: MeetingTitleUpdate, user_id: str = Depends(get_current_user_id)
) -> MeetingSummary:
    record = get_job_repository().update_title(job_id, user_id, payload.title)
    if record is None:
        raise HTTPException(status_code=http_status.HTTP_404_NOT_FOUND, detail="Job não encontrado.")
    return _meeting_summary(record)


@router.delete("/meetings/{job_id}", status_code=http_status.HTTP_204_NO_CONTENT)
async def delete_meeting(job_id: str, user_id: str = Depends(get_current_user_id)) -> Response:
    """Remove a reunião: linha no banco e diretório em storage/jobs/<job_id>.

    Recusa com 409 enquanto o job está em processamento. O motivo é o worker
    ser um PROCESSO SEPARADO: apagar por baixo dele deixaria o pipeline
    terminando um job que já não existe e recriando o diretório para gravar o
    result.json — órfão em disco, exatamente o que a remoção existe para
    evitar. `queued` é permitido porque ali ninguém pegou o job ainda; a
    janela de corrida que sobra (o worker escolhe o job entre a checagem e a
    remoção) é fechada do outro lado, em pipeline_facade.executar().
    """
    repositorio = get_job_repository()
    record = repositorio.get_owned(job_id, user_id)
    if record is None:
        raise HTTPException(status_code=http_status.HTTP_404_NOT_FOUND, detail="Job não encontrado.")

    if record.status in _ESTAGIOS_EM_PROCESSAMENTO:
        raise HTTPException(
            status_code=http_status.HTTP_409_CONFLICT,
            detail=(
                f"Reunião em processamento (status atual: {record.status.value}). "
                "Aguarde terminar para remover."
            ),
        )

    if not repositorio.delete_owned(job_id, user_id):
        raise HTTPException(status_code=http_status.HTTP_404_NOT_FOUND, detail="Job não encontrado.")

    # Banco primeiro, arquivos depois — ver o docstring de delete_owned.
    await run_in_threadpool(storage_repository().delete_job, job_id)
    logger.info("Reunião %s removida a pedido do usuário %s.", job_id, user_id)
    return Response(status_code=http_status.HTTP_204_NO_CONTENT)


@router.get("/status/{job_id}", response_model=JobStatusResponse)
async def get_job_status(job_id: str, user_id: str = Depends(get_current_user_id)) -> JobStatusResponse:
    record = get_job_repository().get_owned(job_id, user_id)
    if record is None:
        raise HTTPException(status_code=http_status.HTTP_404_NOT_FOUND, detail="Job não encontrado.")

    return JobStatusResponse(
        job_id=record.job_id,
        status=record.status,
        error=record.error,
        updated_at=record.updated_at,
    )


@router.get("/resultado/{job_id}", response_model=MeetingResult)
async def get_job_result(job_id: str, user_id: str = Depends(get_current_user_id)) -> MeetingResult:
    record = get_job_repository().get_owned(job_id, user_id)
    if record is None:
        raise HTTPException(status_code=http_status.HTTP_404_NOT_FOUND, detail="Job não encontrado.")

    if record.status != JobStatusValue.DONE:
        raise HTTPException(
            status_code=http_status.HTTP_409_CONFLICT,
            detail=f"Resultado ainda não disponível (status atual: {record.status.value}).",
        )

    resultado = result_repository().load(job_id)
    if resultado is None:
        raise HTTPException(status_code=http_status.HTTP_404_NOT_FOUND, detail="Resultado não encontrado.")

    return resultado


_ESTADOS_FINAIS = {JobStatusValue.DONE, JobStatusValue.ERROR}

# Estágios em que o worker está com o job na mão — DELETE /meetings recusa
# nesses (ver delete_meeting). `queued` fica de fora de propósito.
_ESTAGIOS_EM_PROCESSAMENTO = {
    JobStatusValue.TRANSCRIBING,
    JobStatusValue.DIARIZING,
    JobStatusValue.IDENTIFYING,
    JobStatusValue.SUMMARIZING,
    JobStatusValue.EXTRACTING,
}


def _status_payload(record) -> dict:
    """Mesmo corpo de GET /status/{job_id}, serializado para JSON.

    Deliberadamente idêntico: o app reaproveita um único parser para o
    polling e para o WebSocket, e nunca precisa reconciliar dois formatos
    que descrevem a mesma coisa."""
    return JobStatusResponse(
        job_id=record.job_id,
        status=record.status,
        error=record.error,
        updated_at=record.updated_at,
    ).model_dump(mode="json")


@router.websocket("/ws/{job_id}")
async def job_progress_ws(websocket: WebSocket, job_id: str, token: Optional[str] = None) -> None:
    """Push de progresso do job, do estado atual até done/error.

    Autenticação via query param (?token=access_token) — o handshake de
    WebSocket não permite header Authorization customizado em todo cliente.

    Como o worker é um PROCESSO SEPARADO da API (app/worker.py), não existe
    evento in-process para observar: quem sabe que o job avançou é o banco.
    Então a API observa o banco e empurra para o cliente a cada mudança. O
    push é real do ponto de vista do app (ele não pergunta nada); a espera
    fica do lado do servidor, que é onde ela é barata — SQLite local, uma
    leitura por segundo por conexão aberta.

    A alternativa seria um barramento de eventos (Redis, NOTIFY do Postgres)
    entre worker e API. Foi descartada por ora: exigiria infraestrutura nova
    num servidor compartilhado para ganhar ~1s de latência num pipeline que
    leva dezenas de segundos.

    O polling do app continua sendo o fallback obrigatório, e este handler é
    escrito para não atrapalhá-lo: em qualquer situação de dúvida ele fecha
    a conexão em vez de segurá-la (o app volta ao polling), e o corpo das
    mensagens é igual ao de GET /status.

    Consequência assumida: o que é empurrado é o ESTADO ATUAL a cada
    intervalo, não a sequência completa de transições. Um estágio mais curto
    que `ws_poll_interval_seconds` pode não ser observado — na validação com
    job real, `identifying` (0,07s) e `summarizing` (0,00s, desligado por
    flag) não apareceram. É exatamente o que o polling do app veria, o que
    mantém os dois caminhos consistentes; o histórico completo de transições
    continua no banco (`job_status_events`) para quem precisar medir.
    """
    user_id = user_id_from_ws_token(token)
    if user_id is None:
        # accept() ANTES do close(4401), e a ordem é o ponto: fechar sem
        # aceitar faz o servidor ASGI recusar o próprio handshake com HTTP
        # 403, e o cliente recebe um erro de conexão sem close code nenhum —
        # o 4401 que este código parece emitir jamais chegava ao app.
        # Medido contra a API real em 07/09/2026 ('server rejected WebSocket
        # connection: HTTP 403'); os testes com TestClient não pegam, porque
        # ele entrega a mensagem de close direto pelo ASGI, sem handshake
        # HTTP. Ver test_ws_codigos_de_fechamento_reais.py, que sobe um
        # uvicorn de verdade justamente para esta classe de bug.
        #
        # O custo é aceitar por alguns milissegundos um handshake não
        # autenticado, sem enviar byte nenhum de conteúdo. Vale: sem isso, o
        # 4404 logo abaixo (que já aceita antes) e este se comportariam de
        # formas diferentes parecendo idênticos no código — que foi
        # exatamente como este bug nasceu.
        logger.info("WS /ws/%s fechado com 4401: token de acesso ausente ou inválido.", job_id)
        await websocket.accept()
        await websocket.close(code=4401)
        return

    await websocket.accept()
    repositorio = get_job_repository()
    # get_owned toca o SQLite: fora do event loop, para uma conexão lenta não
    # atrasar as outras requisições da API.
    record = await run_in_threadpool(repositorio.get_owned, job_id, user_id)
    if record is None:
        logger.info(
            "WS /ws/%s fechado com 4404: job inexistente ou de outro dono (user_id do token: %s).",
            job_id,
            user_id,
        )
        await websocket.close(code=4404)
        return

    settings = get_settings()
    limite = time.monotonic() + settings.ws_max_duration_seconds
    ultimo_payload: Optional[dict] = None
    try:
        while True:
            payload = _status_payload(record)
            # Só emite quando algo mudou de fato — um job parado em
            # `transcribing` por 40s não vira 40 mensagens iguais.
            if payload != ultimo_payload:
                await websocket.send_json(payload)
                ultimo_payload = payload

            if record.status in _ESTADOS_FINAIS:
                break
            if time.monotonic() >= limite:
                # Teto de vida da conexão: um job travado não deixa um
                # WebSocket aberto para sempre. O app cai no polling.
                break

            await asyncio.sleep(settings.ws_poll_interval_seconds)
            record = await run_in_threadpool(repositorio.get_owned, job_id, user_id)
            if record is None:
                # O job sumiu com a conexão aberta — hoje só por
                # DELETE /meetings/{job_id} de outra tela do mesmo usuário.
                # Fecha com 4404, o mesmo código de "não existe ou não é seu"
                # da checagem de entrada: sem ele, isto seria um encerramento
                # normal (1000), indistinguível de "o job terminou" para quem
                # está do outro lado.
                logger.info("WS /ws/%s fechado com 4404: job removido com a conexão aberta.", job_id)
                await websocket.close(code=4404)
                return
    except WebSocketDisconnect:
        # Cliente sumiu no meio do caminho — nada a fazer, e não é erro.
        pass
    finally:
        with contextlib.suppress(RuntimeError):
            await websocket.close()
