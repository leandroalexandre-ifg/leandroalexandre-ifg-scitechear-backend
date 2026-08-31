"""Avalia o método AS-Norm (ENABLE_VOICE_ASNORM=true) contra o mesmo cenário
real usado em test_voice_identification_real_regression.py — os 25 embeddings
ECAPA reais (TTS sintético) em
tests/fixtures/voice_identification_real_embeddings.json: 3 perfis
cadastrados, 6 impostores não-outlier e o outlier Reed/Eddy (score 0.9555).

RESULTADO (investigado em 2026-08-31, ver docs/PENDENCIAS.md):

1. Reed/Eddy NÃO é rejeitado pelo AS-Norm — continua um falso positivo, com
   o MESMO score bruto (0.9555) e agora também um z-score enorme (~34.7),
   porque o banco cadastrado só tem 3 pessoas e o cohort de "impostores" de
   cada candidato acaba sendo formado pelas OUTRAS 2 pessoas cadastradas
   (não por uma população externa de impostores). Quando o score bruto do
   candidato já é muito mais alto que o dos outros dois cadastrados — como é
   o caso de Eddy contra praticamente qualquer áudio de teste neste dataset
   — o z-score explode a partir de só 2 pontos, mascarando o problema em vez
   de resolvê-lo.

2. Pior: esse mesmo efeito criou DOIS NOVOS falsos positivos que o threshold
   fixo (0.75) rejeitava corretamente — p_grandma (bruto=0.4126) e p_grandpa
   (bruto=0.6214) — porque ambos passam do piso de sanidade
   (LIMIAR_MINIMO_ABSOLUTO=0.40) e, uma vez lá, o cohort de 2 pontos infla o
   z-score o suficiente para passar também no limiar de z-score e na margem.
   Os outros 4 impostores (rocko, sandy, flo, shelley) continuam rejeitados,
   mas só porque o score bruto deles fica abaixo de 0.40 — ou seja, quem
   segura a rejeição ainda é o piso absoluto herdado do threshold fixo, não
   o AS-Norm em si.

3. As 15 amostras genuínas continuam identificadas corretamente (sem
   regressão aqui).

4. O cohort nunca cai no fallback "menos de 2 impostores" (banco de 3 gera
   sempre exatamente 2 impostores por candidato) — mas isso não ajuda: com
   só 2 pontos, o cohort é estatisticamente instável (variância calculada
   sobre 2 amostras correlacionadas ao mesmo áudio de teste, não uma
   população de impostores fixa e independente). Esse é o problema real,
   mais específico do que "cai em fallback com frequência": o AS-Norm como
   prototipado exige um cohort de impostores INDEPENDENTE do candidato sendo
   avaliado, e aqui ele é derivado dos próprios outros cadastrados — que são
   poucos e re-avaliados a cada novo áudio de teste.

CONCLUSÃO: AS-Norm, como prototipado, não resolve o risco residual
documentado (Reed/Eddy) e piora a taxa de falsos positivos com o tamanho
atual do banco (3 pessoas). NÃO ativar em produção (flag desligada por
padrão). Nenhuma correção foi implementada — ver docs/PENDENCIAS.md.
"""
import json
from pathlib import Path

import pytest
import torch

from app.config import get_settings
from app.services import voice_service

FIXTURE_PATH = Path(__file__).parent / "fixtures" / "voice_identification_real_embeddings.json"


@pytest.fixture(autouse=True)
def asnorm_ligado(monkeypatch):
    monkeypatch.setenv("ENABLE_VOICE_ASNORM", "true")
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
# Caso mais importante: outlier Reed/Eddy — objetivo original do AS-Norm.
# LIMITAÇÃO CONHECIDA, NÃO RESOLVIDA: continua um falso positivo mesmo com
# AS-Norm. Se este teste começar a falhar (isto é, passar a rejeitar),
# investigue a causa antes de assumir que o risco residual foi resolvido.
# ---------------------------------------------------------------------------


def test_outlier_reed_eddy_NAO_e_bloqueado_pelo_asnorm_limitacao_conhecida(dados, banco):
    embedding_reed = torch.tensor(dados["impostor_outlier"]["p_reed"])

    participant_id, score = voice_service.identificar_speaker(embedding_reed, banco)

    assert participant_id == "p_eddy", (
        "Comportamento mudou: o outlier Reed/Eddy deixou de ser um falso "
        "positivo sob AS-Norm. Isso é bom, mas investigue a causa antes de "
        "assumir que o risco residual documentado em docs/PENDENCIAS.md foi "
        "resolvido (o banco de teste continua com só 3 cadastrados)."
    )
    assert score == pytest.approx(0.9555, abs=1e-3)


# ---------------------------------------------------------------------------
# Achado NOVO: com este banco pequeno (3 pessoas), AS-Norm introduz falsos
# positivos que o threshold fixo (0.75) rejeitava corretamente. Documentado
# como limitação conhecida — NÃO tentar "consertar" ajustando os limiares
# aqui sem antes discutir a limitação estrutural (ver docstring do módulo).
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("impostor_pid", ["p_grandma", "p_grandpa"])
def test_impostores_com_score_bruto_acima_do_piso_absoluto_viram_falso_positivo_no_asnorm(
    dados, banco, impostor_pid
):
    embedding = torch.tensor(dados["impostores_nao_outlier"][impostor_pid])

    participant_id, score = voice_service.identificar_speaker(embedding, banco)

    assert participant_id == "p_eddy", (
        f"Comportamento mudou: {impostor_pid} deixou de ser aceito sob "
        "AS-Norm. Bom sinal, mas confira se não foi coincidência de "
        "arredondamento — este teste documenta uma regressão de falso "
        "positivo introduzida pelo AS-Norm com banco pequeno."
    )


@pytest.mark.parametrize("impostor_pid", ["p_rocko", "p_sandy", "p_flo", "p_shelley"])
def test_impostores_com_score_bruto_abaixo_do_piso_absoluto_continuam_rejeitados(
    dados, banco, impostor_pid
):
    # Rejeitados só porque o score bruto fica abaixo de LIMIAR_MINIMO_ABSOLUTO
    # (0.40) — o piso herdado do threshold fixo, não o AS-Norm em si.
    embedding = torch.tensor(dados["impostores_nao_outlier"][impostor_pid])

    participant_id, score = voice_service.identificar_speaker(embedding, banco)

    assert participant_id is None, (
        f"{impostor_pid} (nunca cadastrado) foi identificado como {participant_id} "
        f"(score={score:.4f}) sob AS-Norm."
    )


# ---------------------------------------------------------------------------
# As 15 amostras genuínas continuam identificadas corretamente (sem
# regressão nesse eixo).
# ---------------------------------------------------------------------------


def test_amostras_genuinas_continuam_identificadas_com_asnorm(dados, banco):
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
        f"corretamente sob AS-Norm: {falhas}"
    )


# ---------------------------------------------------------------------------
# Achado: com banco de 3 cadastrados, o cohort nunca cai no fallback formal
# (impostores < 2) — mas isso não torna o AS-Norm eficaz aqui, ver docstring.
# ---------------------------------------------------------------------------


def test_banco_pequeno_nao_aciona_fallback_formal_mas_cohort_fica_degenerado(dados, banco):
    assert len(banco) == 3

    embedding_reed = torch.tensor(dados["impostor_outlier"]["p_reed"])
    embedding_norm = voice_service.normalizar_embedding(embedding_reed)
    scores = {pid: voice_service.comparar_embeddings(embedding_norm, ref) for pid, ref in banco.items()}

    # cada candidato tem exatamente len(banco) - 1 = 2 impostores no cohort
    # -> nunca menos que 2, então _asnorm_scores nunca cai no fallback bruto,
    # mas o cohort de 2 pontos é estatisticamente instável (ver docstring).
    scores_z = voice_service._asnorm_scores(scores, cohort_size=3)
    assert scores_z != scores  # não caiu em fallback
    assert scores_z["p_eddy"] > 10  # z-score inflado a partir de 2 pontos
