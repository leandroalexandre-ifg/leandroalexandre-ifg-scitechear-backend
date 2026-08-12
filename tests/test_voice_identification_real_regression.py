"""Regressão do incidente de falso positivo de identificação biométrica:
participante SEM nenhum embedding cadastrado foi identificado com confiança
como outro participante real. Usa embeddings ECAPA REAIS (não vetores
sintéticos/aleatórios), extraídos de áudio TTS e congelados em
tests/fixtures/voice_identification_real_embeddings.json — reprodutíveis via
os scripts descritos em docs/PENDENCIAS.md.

Trava o comportamento com VOICE_IDENTIFICATION_THRESHOLD=0.75 (recalibrado;
era 0.30). Ver docs/PENDENCIAS.md para o raciocínio completo da calibração
e a limitação estrutural documentada abaixo (caso Reed/Eddy).
"""
import json
from pathlib import Path

import pytest
import torch

from app.config import get_settings
from app.services import voice_service

FIXTURE_PATH = Path(__file__).parent / "fixtures" / "voice_identification_real_embeddings.json"


@pytest.fixture(autouse=True)
def threshold_075(monkeypatch):
    """Trava o threshold em 0.75 para estes testes, independente do que
    estiver em .env — o objetivo aqui é travar o comportamento NESSE valor
    calibrado, não herdar configuração ambiente."""
    monkeypatch.setenv("VOICE_IDENTIFICATION_THRESHOLD", "0.75")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.fixture(scope="module")
def dados():
    return json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))


@pytest.fixture
def banco(dados):
    return {pid: torch.tensor(vec) for pid, vec in dados["enrolled"].items()}


# ---------------------------------------------------------------------------
# Os 6 impostores não-outlier (Fase 1) devem ser rejeitados com threshold 0.75
# ---------------------------------------------------------------------------

IMPOSTORES_NAO_OUTLIER = ["p_rocko", "p_sandy", "p_grandma", "p_grandpa", "p_flo", "p_shelley"]


@pytest.mark.parametrize("impostor_pid", IMPOSTORES_NAO_OUTLIER)
def test_impostor_nao_outlier_e_rejeitado_com_threshold_075(dados, banco, impostor_pid):
    embedding = torch.tensor(dados["impostores_nao_outlier"][impostor_pid])

    participant_id, score = voice_service.identificar_speaker(embedding, banco)

    assert participant_id is None, (
        f"{impostor_pid} (nunca cadastrado) foi identificado como {participant_id} "
        f"(score={score:.4f}) — threshold 0.75 deveria rejeitar, era esse exatamente "
        f"o falso positivo do incidente."
    )


# ---------------------------------------------------------------------------
# As 15 amostras genuínas (3 pessoas x 5 frases novas) continuam identificadas
# corretamente com o threshold mais alto — 0.75 não deveria gerar falsos
# negativos nesses dados (piso genuíno observado foi 0.9157).
# ---------------------------------------------------------------------------


def test_amostras_genuinas_continuam_identificadas_com_threshold_075(dados, banco):
    falhas = []
    total = 0
    for pid_esperado, amostras in dados["genuine_samples"].items():
        for i, vetor in enumerate(amostras):
            total += 1
            embedding = torch.tensor(vetor)
            participant_id, score = voice_service.identificar_speaker(embedding, banco)
            if participant_id != pid_esperado:
                falhas.append((pid_esperado, i, participant_id, score))

    assert not falhas, (
        f"{len(falhas)}/{total} amostras genuínas deixaram de ser identificadas "
        f"corretamente com threshold 0.75: {falhas}"
    )


# ---------------------------------------------------------------------------
# LIMITAÇÃO CONHECIDA, NÃO CORRIGIDA: o caso Reed vs Eddy (score ~0.9555)
# cai DENTRO da própria faixa de match genuíno (piso observado 0.9157) e por
# isso NENHUM threshold plausível de similaridade de cosseno o bloqueia.
# Este teste documenta o risco residual em aberto — não finge que foi
# resolvido. Ver docs/PENDENCIAS.md ("Risco residual"). Se este teste
# começar a falhar (isto é, o outlier passar a ser rejeitado), NÃO trate
# como regressão automática: investigue a causa antes de "consertar" o teste.
# ---------------------------------------------------------------------------


def test_outlier_reed_eddy_NAO_e_bloqueado_pelo_threshold_075_limitacao_conhecida(dados, banco):
    embedding_reed = torch.tensor(dados["impostor_outlier"]["p_reed"])

    participant_id, score = voice_service.identificar_speaker(embedding_reed, banco)

    assert participant_id == "p_eddy", (
        "Comportamento mudou: o outlier Reed/Eddy deixou de ser um falso "
        "positivo. Isso é bom, mas não foi corrigido por este threshold — "
        "investigue a causa (mudança de modelo? de dados?) antes de assumir "
        "que o risco residual documentado em docs/PENDENCIAS.md foi resolvido."
    )
    assert score > 0.9, (
        f"Score esperado próximo de 0.9555 (faixa de match genuíno), veio {score:.4f}"
    )
