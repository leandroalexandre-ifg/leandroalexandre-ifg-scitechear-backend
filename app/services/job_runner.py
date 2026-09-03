"""Monta os repositories e o MeetingPipelineFacade a partir de
app.config.get_settings() — usado tanto por app/api/jobs.py (rotas
/upload e /resultado) quanto pelo worker dedicado (app/worker.py).

Extraído para um módulo próprio (fora de app/api/) para que o worker não
precise importar a camada HTTP só para montar a facade e executar um job.
"""
from pathlib import Path

from app.config import get_settings
from app.repositories.job_repository import get_job_repository
from app.repositories.result_repository import ResultRepository
from app.repositories.storage_repository import StorageRepository
from app.repositories.voice_repository import VoiceRepository
from app.services.pipeline_facade import MeetingPipelineFacade


def storage_repository() -> StorageRepository:
    return StorageRepository(Path(get_settings().storage_root))


def result_repository() -> ResultRepository:
    return ResultRepository(storage_repository())


def build_facade() -> MeetingPipelineFacade:
    voices_root = Path(get_settings().storage_root) / "voices"
    return MeetingPipelineFacade(
        job_repository=get_job_repository(),
        result_repository=result_repository(),
        storage_repository=storage_repository(),
        voice_repository=VoiceRepository(voices_root),
    )


def executar_job(job_id: str) -> None:
    build_facade().executar(job_id)
