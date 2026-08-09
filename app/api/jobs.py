import json
import uuid
from pathlib import Path
from typing import List, Optional

from fastapi import APIRouter, File, Form, HTTPException, UploadFile, WebSocket, WebSocketDisconnect
from fastapi import status as http_status
from pydantic import TypeAdapter, ValidationError

from app.config import get_settings
from app.models.job import JobStatusResponse, JobStatusValue, UploadResponse
from app.models.participant import Participant
from app.models.result import MeetingResult
from app.repositories.job_repository import get_job_repository
from app.repositories.result_repository import ResultRepository
from app.repositories.storage_repository import StorageRepository
from app.repositories.voice_repository import VoiceRepository
from app.services.job_executor import InProcessJobExecutor
from app.services.pipeline_facade import MeetingPipelineFacade

router = APIRouter(tags=["jobs"])

_PARTICIPANTS_ADAPTER = TypeAdapter(List[Participant])


def _storage_repository() -> StorageRepository:
    return StorageRepository(Path(get_settings().storage_root))


def _result_repository() -> ResultRepository:
    return ResultRepository(_storage_repository())


def _build_facade() -> MeetingPipelineFacade:
    voices_root = Path(get_settings().storage_root) / "voices"
    return MeetingPipelineFacade(
        job_repository=get_job_repository(),
        result_repository=_result_repository(),
        storage_repository=_storage_repository(),
        voice_repository=VoiceRepository(voices_root),
    )


def _executar_job(job_id: str) -> None:
    _build_facade().executar(job_id)


# V1: executor in-process (thread). Interface pronta para trocar por uma fila
# real (Celery/Redis) sem mudar as rotas — ver app/services/job_executor.py.
_executor = InProcessJobExecutor(_executar_job)


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
    content = await file.read()
    _storage_repository().save_audio(job_id, content, file.filename or "reuniao.wav")

    get_job_repository().create(
        job_id=job_id,
        title=title,
        participants=parsed_participants,
        expected_speaker_count=expected_speaker_count,
    )

    # Responde rápido; o PipelineFacade percorre os estágios reais em
    # background (transcribing -> ... -> done/error).
    _executor.submit(job_id)

    return UploadResponse(job_id=job_id, status=JobStatusValue.QUEUED)


@router.get("/status/{job_id}", response_model=JobStatusResponse)
async def get_job_status(job_id: str) -> JobStatusResponse:
    record = get_job_repository().get(job_id)
    if record is None:
        raise HTTPException(status_code=http_status.HTTP_404_NOT_FOUND, detail="Job não encontrado.")

    return JobStatusResponse(
        job_id=record.job_id,
        status=record.status,
        error=record.error,
        updated_at=record.updated_at,
    )


@router.get("/resultado/{job_id}", response_model=MeetingResult)
async def get_job_result(job_id: str) -> MeetingResult:
    record = get_job_repository().get(job_id)
    if record is None:
        raise HTTPException(status_code=http_status.HTTP_404_NOT_FOUND, detail="Job não encontrado.")

    if record.status != JobStatusValue.DONE:
        raise HTTPException(
            status_code=http_status.HTTP_409_CONFLICT,
            detail=f"Resultado ainda não disponível (status atual: {record.status.value}).",
        )

    resultado = _result_repository().load(job_id)
    if resultado is None:
        raise HTTPException(status_code=http_status.HTTP_404_NOT_FOUND, detail="Resultado não encontrado.")

    return resultado


@router.websocket("/ws/{job_id}")
async def job_progress_ws(websocket: WebSocket, job_id: str) -> None:
    # Stub: aceita, informa o status atual uma vez e fecha. Push real de
    # progresso (e o fallback de polling continua obrigatório) chega na Fase 8.
    await websocket.accept()
    record = get_job_repository().get(job_id)
    if record is None:
        await websocket.close(code=4404)
        return

    try:
        await websocket.send_json({"job_id": record.job_id, "status": record.status.value})
    except WebSocketDisconnect:
        pass
    finally:
        await websocket.close()
