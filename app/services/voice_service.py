"""Voz: extração de embeddings e identificação de falantes (SpeechBrain ECAPA-TDNN).

Port de legacy/scripts/etapa3_biometria.py — preserva os algoritmos já
validados: extração/normalização de embedding (carregamento lazy do modelo,
resample para 16 kHz, mono, normalização L2), seleção dos maiores segmentos
por cluster, remoção de outliers e concatenação de trechos para gerar um
embedding representativo por speaker. A leitura de WAV usa `soundfile` em vez
de `torchaudio.load` porque versões recentes do torchaudio exigem o backend
`torchcodec` (+ FFmpeg do sistema) para I/O de áudio; `soundfile` é a mesma
biblioteca já usada em legacy/notebooks/transcricao.ipynb para validar WAV.

Única mudança de comportamento em relação ao legado: `aplicar_biometria`
devolve campos SEPARADOS (cluster, participant_id, speaker, identified,
confidence) em vez de concatenar o score no nome (`"Leandro (0.82)"`) — e o
banco é indexado por participant_id, nunca por nome (regra do CLAUDE.md).
Falante não identificado permanece com o cluster original.
"""
import logging
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Union

import soundfile as sf
import torch
import torchaudio
from speechbrain.inference.speaker import EncoderClassifier

from app.config import get_settings
from app.models.result import Segment
from app.services.diarization_service import DiarizationResult, DiarizedSegment

logger = logging.getLogger(__name__)

_DEVICE = "cuda" if torch.cuda.is_available() else "cpu"

_classifier: Optional[EncoderClassifier] = None


def carregar_modelo() -> EncoderClassifier:
    """Carrega o classificador ECAPA sob demanda e reaproveita entre chamadas."""
    global _classifier
    if _classifier is None:
        savedir = Path(get_settings().storage_root) / "models" / "spkrec-ecapa-voxceleb"
        _classifier = EncoderClassifier.from_hparams(
            source=get_settings().voice_model,
            savedir=str(savedir),
            run_opts={"device": _DEVICE},
        )
    return _classifier


def _ler_wav(caminho_wav: Union[str, Path]) -> tuple:
    dados, fs = sf.read(str(caminho_wav), dtype="float32", always_2d=True)  # (amostras, canais)
    return torch.from_numpy(dados.T), fs  # (canais, amostras)


def _carregar_e_normalizar(sinal: torch.Tensor, fs: int) -> torch.Tensor:
    if fs != 16000:
        sinal = torchaudio.functional.resample(sinal, fs, 16000)
    if sinal.shape[0] > 1:  # estéreo -> mono
        sinal = sinal.mean(dim=0, keepdim=True)
    return sinal.to(_DEVICE)


def normalizar_embedding(emb: torch.Tensor) -> torch.Tensor:
    """Normaliza L2 — essencial antes de tirar médias de embeddings."""
    return emb / (emb.norm(p=2) + 1e-8)


def extrair_embedding(caminho_wav: Union[str, Path]) -> torch.Tensor:
    """Extrai o embedding ECAPA-TDNN de um arquivo .wav inteiro (sem normalizar)."""
    classifier = carregar_modelo()
    sinal, fs = _ler_wav(caminho_wav)
    sinal = _carregar_e_normalizar(sinal, fs)

    with torch.no_grad():
        emb = classifier.encode_batch(sinal)

    return emb.squeeze().cpu()


def gerar_embedding(caminho_audio: Union[str, Path]) -> torch.Tensor:
    """Ponto de entrada único para gerar o embedding de um áudio de cadastro.

    Usa exatamente a mesma extração + normalização que o reconhecimento usa
    (abaixo), evitando embeddings incompatíveis por pré-processamento
    diferente entre cadastro e identificação.
    """
    embedding = extrair_embedding(caminho_audio)
    return normalizar_embedding(embedding)


# ---------------------------------------------------------------------------
# Identificação: comparação contra o banco (participant_id -> embedding),
# seleção de segmentos, remoção de outliers e concatenação.
# ---------------------------------------------------------------------------


def comparar_embeddings(emb_a: torch.Tensor, emb_b: torch.Tensor) -> float:
    """Similaridade de cosseno entre dois embeddings (assume ambos já
    normalizados — quem gera embedding via gerar_embedding() ou já tem o
    embedding consolidado do VoiceRepository recebe eles normalizados)."""
    return torch.nn.functional.cosine_similarity(emb_a.unsqueeze(0), emb_b.unsqueeze(0)).item()


def _ler_wav_trecho(caminho_wav: Union[str, Path], inicio: float, fim: float) -> Tuple[torch.Tensor, int]:
    info = sf.info(str(caminho_wav))
    sr = info.samplerate
    frame_offset = max(0, int(inicio * sr))
    num_frames = max(1, int((fim - inicio) * sr))
    dados, fs = sf.read(str(caminho_wav), start=frame_offset, frames=num_frames, dtype="float32", always_2d=True)
    return torch.from_numpy(dados.T), fs


def extrair_embedding_segmento(caminho_audio: Union[str, Path], inicio: float, fim: float) -> torch.Tensor:
    """Extrai o embedding apenas do trecho [inicio, fim] (em segundos) do áudio."""
    classifier = carregar_modelo()
    sinal, fs = _ler_wav_trecho(caminho_audio, inicio, fim)
    sinal = _carregar_e_normalizar(sinal, fs)

    with torch.no_grad():
        emb = classifier.encode_batch(sinal)

    return emb.squeeze().cpu()


def extrair_embedding_concatenado(
    caminho_audio: Union[str, Path], segmentos: List[dict], silencio_s: float = 0.2
) -> torch.Tensor:
    """Concatena fisicamente os trechos de áudio (com um pequeno silêncio
    entre eles) e extrai UM único embedding do resultado. Costuma ser mais
    robusto do que a média de embeddings extraídos separadamente, porque dá
    ao modelo mais contexto temporal contínuo."""
    classifier = carregar_modelo()
    info = sf.info(str(caminho_audio))
    sr = info.samplerate

    pedacos = []
    for seg in segmentos:
        frame_offset = max(0, int(seg["start"] * sr))
        num_frames = max(1, int((seg["end"] - seg["start"]) * sr))
        dados, fs = sf.read(
            str(caminho_audio), start=frame_offset, frames=num_frames, dtype="float32", always_2d=True
        )
        sinal = torch.from_numpy(dados.T)
        if sinal.shape[0] > 1:
            sinal = sinal.mean(dim=0, keepdim=True)

        pedacos.append(sinal)
        # pequeno silêncio entre trechos para não "colar" fonemas
        pedacos.append(torch.zeros(1, int(silencio_s * fs)))

    concatenado = torch.cat(pedacos, dim=1)
    concatenado = _carregar_e_normalizar(concatenado, fs)

    with torch.no_grad():
        emb = classifier.encode_batch(concatenado)

    return emb.squeeze().cpu()


def _remover_outliers(
    embeddings: List[torch.Tensor], segmentos: List[dict]
) -> Tuple[List[torch.Tensor], List[dict]]:
    """Remove trechos cujo embedding diverge muito dos demais — sinal
    provável de erro de diarização (o trecho pegou fala de outra pessoa,
    ruído, etc). Só atua quando há 3+ trechos, para não descartar dados
    demais; nunca descarta tudo — se sobrar vazio, mantém o original."""
    if len(embeddings) < 3:
        return embeddings, segmentos

    outlier_threshold = get_settings().voice_outlier_threshold
    embs_norm = [normalizar_embedding(e) for e in embeddings]
    n = len(embs_norm)

    media_similaridade = []
    for i in range(n):
        sims = [comparar_embeddings(embs_norm[i], embs_norm[j]) for j in range(n) if j != i]
        media_similaridade.append(sum(sims) / len(sims))

    embeddings_ok, segmentos_ok = [], []
    for i, sim_media in enumerate(media_similaridade):
        if sim_media >= outlier_threshold:
            embeddings_ok.append(embeddings[i])
            segmentos_ok.append(segmentos[i])
        else:
            logger.info("Trecho %d descartado por outlier (similaridade média=%.3f)", i + 1, sim_media)

    return (embeddings_ok, segmentos_ok) if embeddings_ok else (embeddings, segmentos)


def identificar_speaker(embedding: torch.Tensor, banco: Dict[str, torch.Tensor]) -> Tuple[Optional[str], float]:
    """Compara um embedding contra o banco (participant_id -> embedding
    consolidado) via similaridade de cosseno. Só aceita um match se:
      1. o score do melhor candidato ultrapassar o limiar de identificação, e
      2. a diferença para o segundo colocado for >= margem mínima.
    Caso contrário, retorna (None, melhor_score) — evita "chutar" a pessoa
    errada. banco é indexado por participant_id, NUNCA por nome."""
    if not banco:
        return None, 0.0

    settings = get_settings()
    embedding = normalizar_embedding(embedding)

    scores = {participant_id: comparar_embeddings(embedding, emb_ref) for participant_id, emb_ref in banco.items()}
    ranking = sorted(scores.items(), key=lambda item: item[1], reverse=True)

    melhor_id, melhor_score = ranking[0]
    segundo_score = ranking[1][1] if len(ranking) > 1 else -1.0
    margem = melhor_score - segundo_score

    if melhor_score < settings.voice_identification_threshold:
        logger.info(
            "Rejeitado -> %s teve o maior score (%.3f) mas abaixo do limiar (%.2f).",
            melhor_id,
            melhor_score,
            settings.voice_identification_threshold,
        )
        return None, melhor_score

    if margem < settings.voice_min_margin:
        logger.info(
            "Rejeitado -> %s (%.3f) muito próximo de %s (%.3f), margem=%.3f < %.2f. Ambíguo demais.",
            melhor_id,
            melhor_score,
            ranking[1][0],
            segundo_score,
            margem,
            settings.voice_min_margin,
        )
        return None, melhor_score

    logger.info("Escolhido -> %s (%.3f, margem=%.3f)", melhor_id, melhor_score, margem)
    return melhor_id, melhor_score


def aplicar_biometria(
    caminho_audio: Union[str, Path],
    diarizacao: DiarizationResult,
    banco: Dict[str, torch.Tensor],
    nomes: Optional[Dict[str, str]] = None,
    duracao_min: float = 1.5,
    max_segmentos: int = 5,
    usar_concatenacao: bool = True,
) -> List[Segment]:
    """Para cada CLUSTER da diarização:
    - pega os N maiores segmentos válidos (duração >= duracao_min);
    - remove outliers (trechos que provavelmente vazaram de outro speaker);
    - extrai UM embedding representativo (concatenação, por padrão);
    - identifica a pessoa com threshold + margem de confiança.

    Devolve os segmentos do contrato canônico (app.models.result.Segment)
    com campos SEPARADOS — cluster, participant_id, speaker, identified,
    confidence — nunca concatenados (ex.: "Leandro (0.82)"). `confidence`
    sempre carrega o melhor score encontrado, mesmo quando `identified` é
    False (rejeitado por threshold ou margem) — necessário para calibrar
    esses thresholds depois, que a spec marca como experimentais. Falante
    não identificado permanece com o cluster original, sem associação
    posicional; `nomes` (participant_id -> display_name) é opcional e só
    preenche o campo `speaker` quando há identificação.
    """
    nomes = nomes or {}

    segmentos_por_cluster: Dict[str, List[DiarizedSegment]] = {}
    for seg in diarizacao.segments:
        segmentos_por_cluster.setdefault(seg.cluster, []).append(seg)

    identificacao_por_cluster: Dict[str, Tuple[Optional[str], float]] = {}

    for cluster, segmentos in segmentos_por_cluster.items():
        segmentos_ordenados = sorted(
            segmentos, key=lambda s: (s.end or 0.0) - (s.start or 0.0), reverse=True
        )
        candidatos = [
            s
            for s in segmentos_ordenados
            if s.start is not None and s.end is not None and (s.end - s.start) >= duracao_min
        ][:max_segmentos]

        if not candidatos:
            logger.info("Cluster %s: nenhum trecho com duração suficiente.", cluster)
            identificacao_por_cluster[cluster] = (None, 0.0)
            continue

        candidatos_dict = [{"start": s.start, "end": s.end} for s in candidatos]

        if usar_concatenacao:
            # extrai embeddings individuais só para detectar outliers, depois
            # gera o embedding final via concatenação de áudio
            embeddings_individuais = [
                extrair_embedding_segmento(caminho_audio, s["start"], s["end"]) for s in candidatos_dict
            ]
            _, candidatos_ok = _remover_outliers(embeddings_individuais, candidatos_dict)
            embedding_final = extrair_embedding_concatenado(caminho_audio, candidatos_ok)
        else:
            embeddings = [
                extrair_embedding_segmento(caminho_audio, s["start"], s["end"]) for s in candidatos_dict
            ]
            embeddings, _ = _remover_outliers(embeddings, candidatos_dict)
            embeddings_norm = [normalizar_embedding(e) for e in embeddings]
            embedding_final = normalizar_embedding(torch.stack(embeddings_norm).mean(dim=0))

        participant_id, score = identificar_speaker(embedding_final, banco)
        identificacao_por_cluster[cluster] = (participant_id, score)

    resultado: List[Segment] = []
    for seg in diarizacao.segments:
        participant_id, score = identificacao_por_cluster.get(seg.cluster, (None, 0.0))
        identified = participant_id is not None

        resultado.append(
            Segment(
                id=f"seg_{seg.id + 1:04d}",
                cluster=seg.cluster,
                participant_id=participant_id,
                speaker=nomes.get(participant_id) if participant_id else None,
                identified=identified,
                # Sempre registra o melhor score, mesmo rejeitado por threshold
                # ou margem — thresholds/margem/outlier são experimentais (spec)
                # e calibrá-los depois exige o score real, não None. O sinal de
                # identificação é o campo `identified`, nunca a ausência de
                # `confidence`.
                confidence=score,
                start=seg.start or 0.0,
                end=seg.end or 0.0,
                text=seg.text,
            )
        )

    return resultado
