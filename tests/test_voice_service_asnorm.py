"""AS-Norm (S-norm adaptativo) em identificar_speaker, atrás de
ENABLE_VOICE_ASNORM (desligado por padrão e em todo ambiente — ver
docs/ASNORM_COHORT_USUARIO.md). O resultado contra embeddings reais fica em
tests/test_voice_identification_real_asnorm.py; aqui, o método isolado com
vetores 2D/3D feitos à mão."""
import math
import statistics

import pytest
import torch

from app.config import get_settings
from app.services import voice_service


def _v(*xs):
    return voice_service.normalizar_embedding(torch.tensor(xs, dtype=torch.float32))


@pytest.fixture
def asnorm(monkeypatch):
    def ligar(**extras):
        monkeypatch.setenv("ENABLE_VOICE_ASNORM", "true")
        for chave, valor in extras.items():
            monkeypatch.setenv(chave, str(valor))
        get_settings.cache_clear()

    yield ligar
    get_settings.cache_clear()


# ---------------------------------------------------------------------------
# asnorm_score — a fórmula
# ---------------------------------------------------------------------------


def test_asnorm_score_e_a_media_dos_zscores_de_teste_e_de_cadastro():
    teste = _v(1.0, 0.2, 0.0)
    cadastro = _v(1.0, 0.0, 0.1)
    cohort = [_v(0.0, 1.0, 0.0), _v(0.3, 1.0, 0.0), _v(0.0, 0.0, 1.0)]
    score = voice_service.comparar_embeddings(teste, cadastro)

    def z(emb):
        s = [voice_service.comparar_embeddings(emb, c) for c in cohort]
        return (score - statistics.mean(s)) / statistics.pstdev(s)

    esperado = 0.5 * (z(teste) + z(cadastro))
    assert voice_service.asnorm_score(score, teste, cadastro, cohort, top_k=10) == pytest.approx(esperado)


def test_asnorm_score_usa_so_os_top_k_impostores_mais_parecidos():
    teste = _v(1.0, 0.0)
    cadastro = _v(1.0, 0.0)
    parecidos = [_v(1.0, 1.0), _v(1.0, 0.8)]
    distante = _v(-1.0, 0.1)

    com_distante = voice_service.asnorm_score(0.9, teste, cadastro, parecidos + [distante], top_k=2)
    sem_distante = voice_service.asnorm_score(0.9, teste, cadastro, parecidos, top_k=2)

    assert com_distante == pytest.approx(sem_distante)


# ---------------------------------------------------------------------------
# identificar_speaker — quando o AS-Norm entra e quando NÃO entra
# ---------------------------------------------------------------------------


def _banco_e_cohort(n_extras):
    banco = {"p1": _v(1.0, 0.0, 0.0), "p2": _v(0.0, 1.0, 0.0)}
    cohort = dict(banco)
    for i in range(n_extras):
        angulo = 0.3 + i * 0.25
        cohort[f"x{i}"] = _v(math.cos(angulo), 0.0, math.sin(angulo))
    return banco, cohort


def test_flag_desligada_ignora_o_cohort(monkeypatch):
    monkeypatch.setenv("ENABLE_VOICE_ASNORM", "false")
    get_settings.cache_clear()
    banco, cohort = _banco_e_cohort(10)
    chamado = []
    monkeypatch.setattr(voice_service, "_identificar_asnorm", lambda *a, **k: chamado.append(1))

    participant_id, _ = voice_service.identificar_speaker(_v(1.0, 0.0, 0.0), banco, cohort=cohort)

    assert not chamado
    assert participant_id == "p1"
    get_settings.cache_clear()


def test_flag_ligada_sem_cohort_usa_threshold_fixo(asnorm, monkeypatch):
    asnorm()
    chamado = []
    monkeypatch.setattr(voice_service, "_identificar_asnorm", lambda *a, **k: chamado.append(1))

    voice_service.identificar_speaker(_v(1.0, 0.0, 0.0), _banco_e_cohort(0)[0])

    assert not chamado


def test_cohort_abaixo_do_minimo_volta_para_o_threshold_fixo(asnorm, monkeypatch):
    # banco de 2 candidatos + 6 extras: cada candidato enxerga 7 impostores < 8
    asnorm(VOICE_ASNORM_MIN_COHORT=8)
    banco, cohort = _banco_e_cohort(6)
    chamado = []
    monkeypatch.setattr(voice_service, "_identificar_asnorm", lambda *a, **k: chamado.append(1))

    voice_service.identificar_speaker(_v(1.0, 0.0, 0.0), banco, cohort=cohort)

    assert not chamado


def test_cohort_no_minimo_usa_asnorm(asnorm, monkeypatch):
    asnorm(VOICE_ASNORM_MIN_COHORT=8)
    banco, cohort = _banco_e_cohort(7)
    chamado = []
    monkeypatch.setattr(voice_service, "_identificar_asnorm", lambda *a, **k: chamado.append(1) or ("p1", 1.0))

    voice_service.identificar_speaker(_v(1.0, 0.0, 0.0), banco, cohort=cohort)

    assert chamado


def test_minimo_configurado_abaixo_de_2_nao_normaliza_contra_um_ponto(asnorm):
    # com 0-1 impostor não há desvio; o piso de 2 vale mesmo com MIN_COHORT=0
    asnorm(VOICE_ASNORM_MIN_COHORT=0)
    banco = {"p1": _v(1.0, 0.0), "p2": _v(0.0, 1.0)}

    participant_id, score = voice_service.identificar_speaker(_v(1.0, 0.0), banco, cohort=dict(banco))

    assert participant_id == "p1"
    assert score == pytest.approx(1.0)


def test_candidato_nunca_entra_no_proprio_cohort(asnorm, monkeypatch):
    asnorm(VOICE_ASNORM_MIN_COHORT=2)
    banco, cohort = _banco_e_cohort(3)
    vistos = {}

    def espiao(score, emb_teste, emb_cadastro, cohort_candidato, top_k):
        vistos[id(emb_cadastro)] = cohort_candidato
        return 0.0

    monkeypatch.setattr(voice_service, "asnorm_score", espiao)
    voice_service.identificar_speaker(_v(1.0, 0.0, 0.0), banco, cohort=cohort)

    for participant_id, emb in banco.items():
        cohort_visto = vistos[id(emb)]
        assert len(cohort_visto) == len(cohort) - 1
        assert all(c is not emb for c in cohort_visto)


def test_asnorm_devolve_o_score_bruto_como_confidence(asnorm):
    asnorm(VOICE_ASNORM_MIN_COHORT=2, VOICE_ASNORM_THRESHOLD=0.0, VOICE_ASNORM_MIN_MARGIN=0.0,
           VOICE_ASNORM_MIN_RAW_SCORE=0.0)
    banco = {"p1": _v(1.0, 0.0, 0.0), "p2": _v(0.0, 1.0, 0.0)}
    cohort = dict(banco)
    # impostores equidistantes dos dois candidatos: o normalizado não inverte o ranking
    cohort.update({f"x{i}": _v(0.1 * i, 0.1 * i, 1.0) for i in range(4)})
    teste = _v(1.0, 0.1, 0.0)

    participant_id, score = voice_service.identificar_speaker(teste, banco, cohort=cohort)

    assert participant_id == "p1"
    assert score == pytest.approx(voice_service.comparar_embeddings(teste, banco["p1"]))


# ---------------------------------------------------------------------------
# _identificar_asnorm — cada condição de rejeição isolada
# ---------------------------------------------------------------------------


def _decidir(asnorm, monkeypatch, normalizados, brutos, **limiares):
    asnorm(VOICE_ASNORM_MIN_COHORT=2, **limiares)
    banco = {pid: _v(1.0, 0.0) for pid in brutos}
    monkeypatch.setattr(voice_service, "asnorm_score", lambda score, *a, **k: normalizados[score])
    return voice_service._identificar_asnorm(_v(1.0, 0.0), banco, brutos, dict(banco), get_settings())


def test_rejeita_por_piso_de_score_bruto(asnorm, monkeypatch):
    pid, score = _decidir(asnorm, monkeypatch, {0.35: 9.0, 0.1: 0.0}, {"p1": 0.35, "p2": 0.1},
                          VOICE_ASNORM_MIN_RAW_SCORE=0.40, VOICE_ASNORM_THRESHOLD=3.0, VOICE_ASNORM_MIN_MARGIN=1.0)
    assert pid is None and score == pytest.approx(0.35)


def test_rejeita_por_score_normalizado_baixo(asnorm, monkeypatch):
    pid, _ = _decidir(asnorm, monkeypatch, {0.8: 2.5, 0.1: 0.0}, {"p1": 0.8, "p2": 0.1},
                      VOICE_ASNORM_MIN_RAW_SCORE=0.40, VOICE_ASNORM_THRESHOLD=3.0, VOICE_ASNORM_MIN_MARGIN=1.0)
    assert pid is None


def test_rejeita_por_margem_normalizada(asnorm, monkeypatch):
    pid, _ = _decidir(asnorm, monkeypatch, {0.8: 4.0, 0.7: 3.5}, {"p1": 0.8, "p2": 0.7},
                      VOICE_ASNORM_MIN_RAW_SCORE=0.40, VOICE_ASNORM_THRESHOLD=3.0, VOICE_ASNORM_MIN_MARGIN=1.0)
    assert pid is None


def test_aceita_quando_as_tres_condicoes_passam(asnorm, monkeypatch):
    pid, score = _decidir(asnorm, monkeypatch, {0.8: 4.0, 0.2: 0.5}, {"p1": 0.8, "p2": 0.2},
                          VOICE_ASNORM_MIN_RAW_SCORE=0.40, VOICE_ASNORM_THRESHOLD=3.0, VOICE_ASNORM_MIN_MARGIN=1.0)
    assert pid == "p1" and score == pytest.approx(0.8)
