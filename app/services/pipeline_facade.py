"""MeetingPipelineFacade — orquestra um job de reunião do início ao fim:

    WhisperX -> pyannote -> SpeechBrain -> formatter -> sumarização ->
    perguntas (explícitas + implícitas) -> resultado canônico persistido.

Atualiza o status do job nos estágios REAIS (spec 6.2): transcribing ->
diarizing -> identifying -> summarizing -> extracting -> done, ou error com
code/message. Erro real de qualquer estágio NUNCA vira resultado fictício —
o job vai para `error` e nada é persistido em ResultRepository.
"""
import logging
from datetime import datetime, timezone
from typing import Dict, List, Tuple

import torch

from app.config import get_settings
from app.models.job import JobError, JobStatusValue
from app.models.participant import Participant
from app.models.result import MeetingResult, Question, ResultMetadata
from app.repositories.job_repository import JobRepository
from app.repositories.result_repository import ResultRepository
from app.repositories.storage_repository import StorageRepository
from app.repositories.voice_repository import VoiceRepository
from app.services import diarization_service, question_service, transcription_service, voice_service
from app.services.transcript_formatter import TranscriptFormatter

logger = logging.getLogger(__name__)


class MeetingPipelineFacade:
    def __init__(
        self,
        job_repository: JobRepository,
        result_repository: ResultRepository,
        storage_repository: StorageRepository,
        voice_repository: VoiceRepository,
    ):
        self._jobs = job_repository
        self._results = result_repository
        self._storage = storage_repository
        self._voices = voice_repository

    def executar(self, job_id: str) -> None:
        job = self._jobs.get(job_id)
        if job is None:
            logger.error("Job %s não encontrado para execução.", job_id)
            return

        audio_path = self._storage.audio_path(job_id)
        if audio_path is None:
            self._marcar_erro(job_id, "AUDIO_NAO_ENCONTRADO", f"Áudio do job {job_id} não encontrado em storage.")
            return

        try:
            self._jobs.update_status(job_id, JobStatusValue.TRANSCRIBING)
            transcricao = transcription_service.transcribe(audio_path)
        except Exception as exc:  # noqa: BLE001 — erro real do estágio vira status error, não crash
            self._marcar_erro(job_id, "TRANSCRIPTION_ERROR", str(exc))
            return

        try:
            self._jobs.update_status(job_id, JobStatusValue.DIARIZING)
            diarizacao = diarization_service.diarizar(
                audio_path, transcricao, expected_speaker_count=job.expected_speaker_count
            )
        except Exception as exc:  # noqa: BLE001
            self._marcar_erro(job_id, "DIARIZATION_ERROR", str(exc))
            return

        try:
            self._jobs.update_status(job_id, JobStatusValue.IDENTIFYING)
            banco, nomes = self._carregar_banco_e_nomes(job.participants)
            segments = voice_service.aplicar_biometria(audio_path, diarizacao, banco, nomes=nomes)
        except Exception as exc:  # noqa: BLE001
            self._marcar_erro(job_id, "IDENTIFICATION_ERROR", str(exc))
            return

        formatter = TranscriptFormatter(segments)

        try:
            self._jobs.update_status(job_id, JobStatusValue.SUMMARIZING)
            # Sumarização só existe como insumo interno de extract_implicit_questions
            # (nenhum outro consumidor) — pulada junto quando a etapa de
            # implícitas está desligada, para não chamar o Ollama à toa.
            if get_settings().enable_implicit_questions:
                resumo = question_service.summarize_meeting(formatter)
            else:
                resumo = ""
        except Exception as exc:  # noqa: BLE001
            self._marcar_erro(job_id, "SUMMARIZATION_ERROR", str(exc))
            return

        try:
            self._jobs.update_status(job_id, JobStatusValue.EXTRACTING)
            perguntas = self._extrair_perguntas(formatter, resumo)
        except Exception as exc:  # noqa: BLE001
            self._marcar_erro(job_id, "EXTRACTION_ERROR", str(exc))
            return

        resultado = self._montar_resultado(job_id, segments, perguntas)
        self._results.save(resultado)
        self._jobs.update_status(job_id, JobStatusValue.DONE)

    def _carregar_banco_e_nomes(
        self, participants: List[Participant]
    ) -> Tuple[Dict[str, torch.Tensor], Dict[str, str]]:
        """banco só inclui participantes com perfil de voz cadastrado
        (VoiceRepository); nomes vem do próprio job (contrato do /upload),
        não do display_name do enrollment — é o nome que o Flutter mandou
        para ESTA reunião."""
        banco: Dict[str, torch.Tensor] = {}
        nomes: Dict[str, str] = {}
        for participant in participants:
            embedding = self._voices.load_embedding(participant.id)
            if embedding is not None:
                banco[participant.id] = embedding
            nomes[participant.id] = participant.name
        return banco, nomes

    def _extrair_perguntas(self, formatter: TranscriptFormatter, resumo: str) -> List[Question]:
        settings = get_settings()
        explicitas = question_service.extract_explicit_questions(formatter)

        # Etapa inteira de implícitas desligada por ENABLE_IMPLICIT_QUESTIONS
        # (default False, temporário — ver docs/PENDENCIAS.md). Diferente do
        # refinador: aqui não chamamos extract_implicit_questions nenhuma vez,
        # não só o refinamento por cima dela.
        if not settings.enable_implicit_questions:
            return explicitas

        implicitas = question_service.extract_implicit_questions(formatter, resumo)
        if settings.enable_implicit_refinement:
            implicitas = question_service.refine_implicit_questions(implicitas, formatter)
        return explicitas + implicitas

    def _montar_resultado(self, job_id: str, segments, perguntas: List[Question]) -> MeetingResult:
        settings = get_settings()
        return MeetingResult(
            job_id=job_id,
            segments=segments,
            questions=perguntas,
            metadata=ResultMetadata(
                whisperx_model=settings.whisperx_model,
                diarization_model=settings.diarization_model,
                voice_model=settings.voice_model,
                llm_model=settings.ollama_model,
                generated_at=datetime.now(timezone.utc),
                stub=False,
            ),
        )

    def _marcar_erro(self, job_id: str, code: str, message: str) -> None:
        logger.error("Job %s falhou em %s: %s", job_id, code, message)
        self._jobs.update_status(job_id, JobStatusValue.ERROR, error=JobError(code=code, message=message))
