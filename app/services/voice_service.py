"""Extração de embeddings de voz (SpeechBrain ECAPA-TDNN).

Port de legacy/scripts/etapa3_biometria.py — preserva o algoritmo de extração
e normalização já validado (carregamento lazy do modelo, resample para
16 kHz, mono, normalização L2). A leitura de WAV usa `soundfile` em vez de
`torchaudio.load` porque versões recentes do torchaudio exigem o backend
`torchcodec` (+ FFmpeg do sistema) para I/O de áudio; `soundfile` é a mesma
biblioteca já usada em legacy/notebooks/transcricao.ipynb para validar WAV.

A lógica de identificação (comparação contra o banco, thresholds, remoção de
outliers) é adicionada na Fase 4, neste mesmo módulo.
"""
from pathlib import Path
from typing import Optional, Union

import soundfile as sf
import torch
import torchaudio
from speechbrain.inference.speaker import EncoderClassifier

from app.config import get_settings

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
    depois (Fase 4), evitando embeddings incompatíveis por pré-processamento
    diferente entre cadastro e identificação.
    """
    embedding = extrair_embedding(caminho_audio)
    return normalizar_embedding(embedding)
