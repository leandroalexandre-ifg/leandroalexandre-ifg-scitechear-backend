"""AS-Norm contra os embeddings ECAPA reais (TTS) de
tests/fixtures/voice_identification_real_embeddings.json — o mesmo cenário de
test_voice_identification_real_regression.py. Trava os achados de
docs/ASNORM_COHORT_USUARIO.md (medição completa em
docs/repro/asnorm-cohort/):

1. Com o banco do fixture (3 perfis), cohort da reunião e cohort do usuário
   são o MESMO conjunto, e o mínimo de cohort manda a decisão de volta ao
   threshold fixo — ligar a flag num banco pequeno não reproduz os falsos
   positivos da primeira tentativa.
2. Sem esse mínimo, os falsos positivos grandma/grandpa voltam — é o que o
   mínimo existe para impedir.
3. Com o banco "crescido" (as outras identidades do fixture cadastradas, fora
   da reunião, cohort de 8), grandma/grandpa são rejeitados pelo próprio
   score normalizado, sem depender do piso bruto.
4. Reed/Eddy NÃO é resolvido: o par é indistinguível para o ECAPA neste
   fixture. Sem Reed no banco, Reed passa como Eddy; com Reed no banco, as
   genuínas de Eddy passam a ser rejeitadas.

TTS, não voz humana — indício, não calibração.
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
    for chave, valor in {
        "VOICE_IDENTIFICATION_THRESHOLD": "0.75",
        "VOICE_MIN_MARGIN": "0.05",
        "VOICE_ASNORM_MIN_COHORT": "8",
        "VOICE_ASNORM_TOP_K": "10",
        "VOICE_ASNORM_THRESHOLD": "3.0",
        "VOICE_ASNORM_MIN_MARGIN": "1.0",
        "VOICE_ASNORM_MIN_RAW_SCORE": "0.40",
    }.items():
        monkeypatch.setenv(chave, valor)
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.fixture(scope="module")
def dados():
    return json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))


@pytest.fixture
def banco(dados):
    return {pid: torch.tensor(v) for pid, v in dados["enrolled"].items()}


@pytest.fixture
def extras(dados):
    todos = {pid: torch.tensor(v) for pid, v in dados["impostores_nao_outlier"].items()}
    todos.update({pid: torch.tensor(v) for pid, v in dados["impostor_outlier"].items()})
    return todos


def _cohort_crescido(banco, extras, sem):
    """Banco do usuário = os 3 da reunião + as identidades extras, menos
    `sem` (quem está sob teste não tem perfil: leave-one-out)."""
    cohort = dict(banco)
    cohort.update({pid: emb for pid, emb in extras.items() if pid not in sem})
    return cohort


# 1 -------------------------------------------------------------------------


@pytest.mark.parametrize("impostor", ["p_grandma", "p_grandpa"])
def test_banco_do_fixture_cai_no_threshold_fixo_e_rejeita_grandma_grandpa(banco, extras, impostor):
    participant_id, _ = voice_service.identificar_speaker(extras[impostor], banco, cohort=dict(banco))
    assert participant_id is None


def test_banco_do_fixture_mantem_o_comportamento_do_threshold_fixo_em_reed(banco, extras):
    # mesma limitação conhecida de test_voice_identification_real_regression.py
    participant_id, score = voice_service.identificar_speaker(extras["p_reed"], banco, cohort=dict(banco))
    assert participant_id == "p_eddy"
    assert score == pytest.approx(0.9555, abs=1e-3)


# 2 -------------------------------------------------------------------------


@pytest.mark.parametrize("impostor", ["p_grandma", "p_grandpa"])
def test_sem_o_minimo_o_cohort_de_2_reproduz_os_falsos_positivos(monkeypatch, banco, extras, impostor):
    monkeypatch.setenv("VOICE_ASNORM_MIN_COHORT", "2")
    get_settings.cache_clear()

    participant_id, _ = voice_service.identificar_speaker(extras[impostor], banco, cohort=dict(banco))

    assert participant_id == "p_eddy", (
        f"{impostor} deixou de ser falso positivo com cohort de 2 — o motivo do "
        "VOICE_ASNORM_MIN_COHORT mudou; revise docs/ASNORM_COHORT_USUARIO.md."
    )


# 3 -------------------------------------------------------------------------


@pytest.mark.parametrize("impostor", ["p_rocko", "p_sandy", "p_grandma", "p_grandpa", "p_flo", "p_shelley"])
def test_banco_crescido_rejeita_impostores_nao_outlier(banco, extras, impostor):
    cohort = _cohort_crescido(banco, extras, sem={impostor})
    participant_id, score = voice_service.identificar_speaker(extras[impostor], banco, cohort=cohort)
    assert participant_id is None, f"{impostor} identificado como {participant_id} (bruto={score:.4f})"


@pytest.mark.parametrize("impostor", ["p_grandma", "p_grandpa"])
def test_banco_crescido_rejeita_grandma_grandpa_sem_depender_do_piso_bruto(monkeypatch, banco, extras, impostor):
    monkeypatch.setenv("VOICE_ASNORM_MIN_RAW_SCORE", "0.0")
    get_settings.cache_clear()
    cohort = _cohort_crescido(banco, extras, sem={impostor})

    participant_id, _ = voice_service.identificar_speaker(extras[impostor], banco, cohort=cohort)

    assert participant_id is None


def test_banco_crescido_identifica_genuinas_de_joana_e_luciana(dados, banco, extras):
    cohort = _cohort_crescido(banco, extras, sem=set())
    for pid in ["p_joana", "p_luciana"]:
        for vetor in dados["genuine_samples"][pid]:
            participant_id, _ = voice_service.identificar_speaker(torch.tensor(vetor), banco, cohort=cohort)
            assert participant_id == pid


# 4 -------------------------------------------------------------------------


def test_reed_sem_perfil_continua_falso_positivo_limitacao_conhecida(banco, extras):
    cohort = _cohort_crescido(banco, extras, sem={"p_reed"})

    participant_id, score = voice_service.identificar_speaker(extras["p_reed"], banco, cohort=cohort)

    assert participant_id == "p_eddy", (
        "Reed deixou de passar como Eddy com o banco crescido. Bom sinal, mas "
        "confira a causa antes de dar o risco residual por resolvido."
    )
    assert score == pytest.approx(0.9555, abs=1e-3)


def test_com_reed_no_banco_as_genuinas_de_eddy_sao_rejeitadas(dados, banco, extras):
    cohort = _cohort_crescido(banco, extras, sem=set())
    for vetor in dados["genuine_samples"]["p_eddy"]:
        participant_id, _ = voice_service.identificar_speaker(torch.tensor(vetor), banco, cohort=cohort)
        assert participant_id is None


def test_sem_reed_no_banco_as_genuinas_de_eddy_sao_identificadas(dados, banco, extras):
    cohort = _cohort_crescido(banco, extras, sem={"p_reed"})
    for vetor in dados["genuine_samples"]["p_eddy"]:
        participant_id, _ = voice_service.identificar_speaker(torch.tensor(vetor), banco, cohort=cohort)
        assert participant_id == "p_eddy"
