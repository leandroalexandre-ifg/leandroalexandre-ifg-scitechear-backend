"""Testes do método de decisão AS-Norm (Adaptive Score Normalization) em
identificar_speaker, atrás da flag ENABLE_VOICE_ASNORM (default False — ver
app/config.py e docs/PENDENCIAS.md). Com a flag desligada, o comportamento
é o threshold fixo de sempre (coberto em test_voice_service_identification.py
e test_voice_identification_real_regression.py, não alterados aqui).

Para o resultado com dados reais do banco (outlier Reed/Eddy, impostores,
genuínas) e o achado sobre o cohort degenerado com bancos pequenos, ver
tests/test_voice_identification_real_asnorm.py.
"""
import statistics
from types import SimpleNamespace

import pytest
import torch

from app.config import get_settings
from app.services import voice_service


@pytest.fixture
def asnorm_ligado(monkeypatch):
    monkeypatch.setenv("ENABLE_VOICE_ASNORM", "true")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


# ---------------------------------------------------------------------------
# _asnorm_scores — cohort e fallback (função pura, testada isolada)
# ---------------------------------------------------------------------------


def test_asnorm_scores_normaliza_pelo_zscore_do_cohort():
    scores = {"a": 0.9, "b": 0.5, "c": 0.4, "d": 0.3}
    resultado = voice_service._asnorm_scores(scores, cohort_size=3)

    cohort_a = [0.5, 0.4, 0.3]
    media = statistics.mean(cohort_a)
    desvio = statistics.pstdev(cohort_a)
    assert resultado["a"] == pytest.approx((0.9 - media) / desvio)


def test_asnorm_scores_usa_apenas_top_n_do_cohort():
    scores = {"a": 0.9, "b": 0.8, "c": 0.7, "d": 0.1}
    resultado = voice_service._asnorm_scores(scores, cohort_size=2)

    cohort_a = [0.8, 0.7]  # top-2 de {b, c, d}; "d" (0.1) fica de fora
    media = statistics.mean(cohort_a)
    desvio = statistics.pstdev(cohort_a)
    assert resultado["a"] == pytest.approx((0.9 - media) / desvio)


def test_asnorm_scores_fallback_com_menos_de_2_impostores():
    # banco de 2 pessoas -> cada candidato só tem 1 "impostor" -> cohort
    # pequeno demais pra normalizar, cai de volta pro score bruto
    scores = {"a": 0.9, "b": 0.2}
    resultado = voice_service._asnorm_scores(scores, cohort_size=3)
    assert resultado == scores


def test_asnorm_scores_fallback_com_banco_de_1():
    scores = {"a": 0.5}
    resultado = voice_service._asnorm_scores(scores, cohort_size=3)
    assert resultado == scores


# ---------------------------------------------------------------------------
# _identificar_speaker_asnorm — as três condições de aceite, isoladas via
# settings sintéticos (os limiares de produção ficam nos testes com dados
# reais; aqui o objetivo é isolar cada ramo de decisão individualmente)
# ---------------------------------------------------------------------------


def _settings(**overrides):
    base = dict(voice_min_absolute_score=0.0, voice_zscore_threshold=0.0, voice_zscore_margin=0.0, voice_cohort_size=3)
    base.update(overrides)
    return SimpleNamespace(**base)


def test_identificar_speaker_asnorm_rejeita_por_piso_absoluto():
    # z-score de p1 (2.4) passaria no limiar, mas o score bruto (0.35) não
    # ultrapassa o piso de sanidade -> rejeitado antes de olhar pro z-score
    scores_brutos = {"p1": 0.35, "p2": 0.0, "p3": -0.5}
    settings = _settings(voice_min_absolute_score=0.40, voice_zscore_threshold=1.0, voice_zscore_margin=0.1)

    participant_id, score = voice_service._identificar_speaker_asnorm(scores_brutos, settings)

    assert participant_id is None
    assert score == pytest.approx(0.35)


def test_identificar_speaker_asnorm_rejeita_por_zscore_baixo():
    # score bruto (0.42) passa o piso, mas o z-score (1.095) não se destaca
    # o suficiente do cohort (p2=0.41, p3=0.20)
    scores_brutos = {"p1": 0.42, "p2": 0.41, "p3": 0.20}
    settings = _settings(voice_min_absolute_score=0.0, voice_zscore_threshold=2.0, voice_zscore_margin=0.1)

    participant_id, score = voice_service._identificar_speaker_asnorm(scores_brutos, settings)

    assert participant_id is None
    assert score == pytest.approx(0.42)


def test_identificar_speaker_asnorm_rejeita_por_margem_ambigua():
    # p1 (z=1.518) e p2 (z=1.314) ambos destacados do restante, mas
    # margem entre eles (0.204) é ambígua demais
    scores_brutos = {"p1": 0.99, "p2": 0.9, "p3": -0.9, "p4": -0.95, "p5": -0.98}
    settings = _settings(voice_min_absolute_score=0.0, voice_zscore_threshold=1.0, voice_zscore_margin=0.5)

    participant_id, score = voice_service._identificar_speaker_asnorm(scores_brutos, settings)

    assert participant_id is None
    assert score == pytest.approx(0.99)


def test_identificar_speaker_asnorm_aceita_quando_as_tres_condicoes_passam():
    scores_brutos = {"p1": 0.9, "p2": 0.2, "p3": 0.1}
    settings = _settings(voice_min_absolute_score=0.4, voice_zscore_threshold=1.0, voice_zscore_margin=0.5)

    participant_id, score = voice_service._identificar_speaker_asnorm(scores_brutos, settings)

    assert participant_id == "p1"
    assert score == pytest.approx(0.9)


def test_identificar_speaker_asnorm_com_cohort_em_fallback_usa_score_bruto():
    # banco de 2 -> _asnorm_scores cai pro score bruto; as três condições
    # continuam se aplicando, só que sobre o score bruto em vez do z-score
    scores_brutos = {"p1": 0.9, "p2": 0.1}
    settings = _settings(voice_min_absolute_score=0.4, voice_zscore_threshold=0.5, voice_zscore_margin=0.3)

    participant_id, score = voice_service._identificar_speaker_asnorm(scores_brutos, settings)

    assert participant_id == "p1"
    assert score == pytest.approx(0.9)


# ---------------------------------------------------------------------------
# identificar_speaker — dispatch pela flag ENABLE_VOICE_ASNORM
# ---------------------------------------------------------------------------


def test_identificar_speaker_flag_desligada_usa_threshold_fixo(monkeypatch):
    chamado = {}
    monkeypatch.setattr(
        voice_service,
        "_identificar_speaker_asnorm",
        lambda *a, **k: chamado.setdefault("asnorm", True),
    )
    banco = {"p1": torch.tensor([1.0, 0.0])}
    embedding = torch.tensor([1.0, 0.0])

    participant_id, score = voice_service.identificar_speaker(embedding, banco)

    assert "asnorm" not in chamado
    assert participant_id == "p1"


def test_identificar_speaker_flag_ligada_usa_asnorm(asnorm_ligado, monkeypatch):
    chamado = {}
    monkeypatch.setattr(
        voice_service,
        "_identificar_speaker_threshold_fixo",
        lambda *a, **k: chamado.setdefault("threshold_fixo", True),
    )
    banco = {
        "p1": torch.tensor([1.0, 0.0]),
        "p2": torch.tensor([0.0, 1.0]),
        "p3": torch.tensor([-1.0, 0.0]),
    }
    embedding = torch.tensor([1.0, 0.0])

    participant_id, score = voice_service.identificar_speaker(embedding, banco)

    assert "threshold_fixo" not in chamado
    assert participant_id == "p1"
