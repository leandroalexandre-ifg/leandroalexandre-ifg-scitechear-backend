"""TranscriptionService — WhisperX (transcrição + alinhamento temporal).

Port de legacy/notebooks/transcricao.ipynb: preserva o algoritmo (modelo
turbo, idioma configurável, batch_size configurável, float16 em CUDA / int8
em CPU, alinhamento temporal via WhisperX), removendo Google Drive/Colab e
os paths fixos do notebook. `words` é preservado como artefato interno —
não faz parte do contrato canônico HTTP (app/models/result.py), que só
expõe segmentos com id/start/end/text.

Carrega e libera os modelos (transcrição e alinhamento) a cada chamada,
igual ao notebook original: evita manter dois modelos pesados na GPU ao
mesmo tempo quando as outras etapas do pipeline (diarização, biometria)
rodam em sequência no mesmo processo/job (Fase 6).
"""
import gc
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional, Tuple, Union

import torch
import whisperx
from pydantic import BaseModel

from app.config import get_settings


class TranscribedWord(BaseModel):
    word: Optional[str] = None
    start: Optional[float] = None
    end: Optional[float] = None
    score: Optional[float] = None


class TranscribedSegment(BaseModel):
    id: int
    start: Optional[float] = None
    end: Optional[float] = None
    text: str
    words: List[TranscribedWord] = []


class TranscriptionMetadata(BaseModel):
    audio_file: str
    generated_at: datetime
    pipeline_stage: str = "transcricao"
    model: str
    language: str
    duration_seconds: float
    sample_rate: int


class TranscriptionResult(BaseModel):
    metadata: TranscriptionMetadata
    segments: List[TranscribedSegment]


def _device_e_compute_type() -> Tuple[str, str]:
    if torch.cuda.is_available():
        return "cuda", "float16"
    return "cpu", "int8"


def transcribe(audio_path: Union[str, Path], language: Optional[str] = None) -> TranscriptionResult:
    """Transcreve e alinha um áudio via WhisperX.

    `audio_path` deve ser um WAV 16 kHz mono (contrato do /upload); o
    `whisperx.load_audio` reamostra internamente se necessário, igual ao
    notebook original.
    """
    settings = get_settings()
    device, compute_type = _device_e_compute_type()
    idioma_configurado = language or settings.whisperx_language

    audio_path_str = str(audio_path)
    audio = whisperx.load_audio(audio_path_str)
    duration_seconds = len(audio) / 16000

    model = whisperx.load_model(
        settings.whisperx_model,
        device=device,
        compute_type=compute_type,
        language=idioma_configurado,
    )
    result = model.transcribe(audio, batch_size=settings.whisperx_batch_size)
    detected_language = result.get("language", idioma_configurado)

    del model
    gc.collect()
    if device == "cuda":
        torch.cuda.empty_cache()

    align_model, align_metadata = whisperx.load_align_model(language_code=detected_language, device=device)
    result_aligned = whisperx.align(
        result["segments"],
        align_model,
        align_metadata,
        audio,
        device,
        return_char_alignments=False,
    )

    del align_model
    gc.collect()
    if device == "cuda":
        torch.cuda.empty_cache()

    return _build_result(
        result_aligned=result_aligned,
        audio_path=audio_path_str,
        duration_seconds=duration_seconds,
        detected_language=detected_language,
        model_name=settings.whisperx_model,
    )


def _build_result(
    result_aligned: dict,
    audio_path: str,
    duration_seconds: float,
    detected_language: str,
    model_name: str,
) -> TranscriptionResult:
    segments: List[TranscribedSegment] = []
    for i, seg in enumerate(result_aligned["segments"]):
        words = [
            TranscribedWord(word=w.get("word"), start=w.get("start"), end=w.get("end"), score=w.get("score"))
            for w in seg.get("words", [])
            # descarta palavras sem timestamp (ex.: falhas pontuais de alinhamento)
            if w.get("start") is not None and w.get("end") is not None
        ]
        segments.append(
            TranscribedSegment(
                id=i,
                start=seg.get("start"),
                end=seg.get("end"),
                text=(seg.get("text") or "").strip(),
                words=words,
            )
        )

    metadata = TranscriptionMetadata(
        audio_file=Path(audio_path).name,
        generated_at=datetime.now(timezone.utc),
        model=model_name,
        language=detected_language,
        duration_seconds=round(duration_seconds, 3),
        sample_rate=16000,
    )

    return TranscriptionResult(metadata=metadata, segments=segments)
