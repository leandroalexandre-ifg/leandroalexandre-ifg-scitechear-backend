"""DiarizationService — pyannote (clusters de fala).

Port de legacy/scripts/etapa2b_diarizacao.py: preserva o algoritmo de merge
por maior sobreposição temporal entre segmentos diarizados (pyannote) e
segmentos de transcrição (WhisperX). Diferenças em relação ao legado:

- carregamento do pipeline é lazy — importar este módulo NUNCA falha por
  falta de HF_TOKEN; só o primeiro uso real de `diarizar()` exige o token;
- MIN_SPEAKERS=4 / MAX_SPEAKERS=7 fixos foram removidos. Os limites agora
  vêm de config/env (`DIARIZATION_MIN_SPEAKERS`/`DIARIZATION_MAX_SPEAKERS`);
  `expected_speaker_count` (pista opcional do job) vira `max_speakers` por
  padrão, e só vira `num_speakers` exato quando `exact_speaker_count=True`
  for pedido explicitamente pelo chamador.

Diarização produz CLUSTER (SPEAKER_00, SPEAKER_01, ...) — não identidade.
A identificação por participant_id é responsabilidade do voice_service
(SpeechBrain), numa etapa separada (diarização ≠ biometria).
"""
import logging
from pathlib import Path
from typing import Dict, List, Optional, Union

import torch
from pydantic import BaseModel, Field
from pyannote.audio import Pipeline

from app.config import get_settings
from app.services.transcription_service import TranscribedWord, TranscriptionResult

logger = logging.getLogger(__name__)

_pipeline: Optional[Pipeline] = None


class DiarizedSegment(BaseModel):
    id: int
    cluster: str
    start: Optional[float] = None
    end: Optional[float] = None
    text: str
    words: List[TranscribedWord] = Field(default_factory=list)


class DiarizationResult(BaseModel):
    segments: List[DiarizedSegment]


def carregar_pipeline() -> Pipeline:
    """Carrega o pipeline de diarização sob demanda e reaproveita entre
    chamadas. Só aqui (não no import do módulo) é que a falta de HF_TOKEN
    vira erro."""
    global _pipeline
    if _pipeline is None:
        settings = get_settings()
        if not settings.hf_token:
            raise RuntimeError(
                "HF_TOKEN não configurado — necessário para carregar o pipeline de diarização."
            )
        _pipeline = Pipeline.from_pretrained(settings.diarization_model, token=settings.hf_token)
        if torch.cuda.is_available():
            _pipeline.to(torch.device("cuda"))
    return _pipeline


def _atribuir_clusters(
    segmentos_transcricao: List[dict], segmentos_diarizados: List[dict]
) -> List[str]:
    """Para cada segmento de transcrição, retorna o cluster (SPEAKER_XX) de
    maior sobreposição temporal. 'Desconhecido' se não houver sobreposição
    com nenhum trecho diarizado."""
    clusters = []
    for segmento in segmentos_transcricao:
        inicio = segmento["start"]
        fim = segmento["end"]

        melhor_cluster = "Desconhecido"
        maior_overlap = 0.0

        for diarizado in segmentos_diarizados:
            overlap = min(diarizado["end"], fim) - max(diarizado["start"], inicio)
            if overlap > maior_overlap:
                maior_overlap = overlap
                melhor_cluster = diarizado["speaker"]

        clusters.append(melhor_cluster)
    return clusters


def diarizar(
    caminho_audio: Union[str, Path],
    transcricao: TranscriptionResult,
    expected_speaker_count: Optional[int] = None,
    exact_speaker_count: bool = False,
) -> DiarizationResult:
    """Executa a diarização e devolve os segmentos da transcrição, cada um
    com o cluster (SPEAKER_XX) de maior sobreposição temporal atribuído.
    """
    settings = get_settings()
    pipeline = carregar_pipeline()

    if exact_speaker_count and expected_speaker_count is not None:
        diarization_output = pipeline(str(caminho_audio), num_speakers=expected_speaker_count)
    else:
        min_speakers = settings.diarization_min_speakers
        max_speakers = expected_speaker_count or settings.diarization_max_speakers
        diarization_output = pipeline(
            str(caminho_audio), min_speakers=min_speakers, max_speakers=max_speakers
        )

    diarization = diarization_output.speaker_diarization

    segmentos_diarizados: List[dict] = []
    duracao_por_speaker: Dict[str, float] = {}
    for segment, _, speaker in diarization.itertracks(yield_label=True):
        segmentos_diarizados.append({"start": segment.start, "end": segment.end, "speaker": speaker})
        duracao_por_speaker[speaker] = duracao_por_speaker.get(speaker, 0.0) + (segment.end - segment.start)

    logger.info("Speakers encontrados pelo pyannote: %s", sorted(duracao_por_speaker))
    for speaker, tempo in sorted(duracao_por_speaker.items(), key=lambda item: -item[1]):
        if tempo < 15:
            logger.warning("Pouca duração de fala para %s: %.1fs", speaker, tempo)

    clusters = _atribuir_clusters(
        [{"start": s.start, "end": s.end} for s in transcricao.segments],
        segmentos_diarizados,
    )

    segmentos = [
        DiarizedSegment(id=s.id, cluster=cluster, start=s.start, end=s.end, text=s.text, words=s.words)
        for s, cluster in zip(transcricao.segments, clusters)
    ]
    return DiarizationResult(segments=segmentos)
