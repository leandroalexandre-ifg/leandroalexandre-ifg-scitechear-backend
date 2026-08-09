import math

import pytest
import torch

from app.services import voice_service
from app.services.diarization_service import DiarizationResult, DiarizedSegment


# ---------------------------------------------------------------------------
# comparar_embeddings
# ---------------------------------------------------------------------------


def test_comparar_embeddings_identicos_e_1():
    v = torch.tensor([1.0, 0.0])
    assert math.isclose(voice_service.comparar_embeddings(v, v), 1.0, abs_tol=1e-6)


def test_comparar_embeddings_ortogonais_e_0():
    a = torch.tensor([1.0, 0.0])
    b = torch.tensor([0.0, 1.0])
    assert math.isclose(voice_service.comparar_embeddings(a, b), 0.0, abs_tol=1e-6)


# ---------------------------------------------------------------------------
# identificar_speaker — aceito / rejeitado por threshold / rejeitado por margem
# ---------------------------------------------------------------------------


def test_identificar_speaker_aceita_quando_score_alto_e_sem_ambiguidade():
    banco = {"p1": torch.tensor([1.0, 0.0])}
    embedding = torch.tensor([1.0, 0.0])

    participant_id, score = voice_service.identificar_speaker(embedding, banco)

    assert participant_id == "p1"
    assert score > 0.99


def test_identificar_speaker_rejeita_por_threshold():
    banco = {"p1": torch.tensor([1.0, 0.0])}
    embedding = torch.tensor([0.0, 1.0])  # ortogonal -> score ~0.0

    participant_id, score = voice_service.identificar_speaker(embedding, banco)

    assert participant_id is None
    assert score < voice_service.get_settings().voice_identification_threshold


def test_identificar_speaker_rejeita_por_margem_ambigua():
    # dois candidatos quase colados em ângulo (diferença de score < margem mínima)
    embedding = torch.tensor([math.cos(0.0), math.sin(0.0)])
    banco = {
        "p1": torch.tensor([math.cos(0.01), math.sin(0.01)]),
        "p2": torch.tensor([math.cos(0.02), math.sin(0.02)]),
    }

    participant_id, score = voice_service.identificar_speaker(embedding, banco)

    assert participant_id is None
    assert score > voice_service.get_settings().voice_identification_threshold


def test_identificar_speaker_banco_vazio_retorna_none():
    participant_id, score = voice_service.identificar_speaker(torch.tensor([1.0, 0.0]), {})
    assert participant_id is None
    assert score == 0.0


# ---------------------------------------------------------------------------
# _remover_outliers
# ---------------------------------------------------------------------------


def test_remover_outliers_nao_atua_com_menos_de_3():
    embeddings = [torch.tensor([1.0, 0.0]), torch.tensor([0.0, 1.0])]
    segmentos = [{"idx": 0}, {"idx": 1}]

    ok_embeddings, ok_segmentos = voice_service._remover_outliers(embeddings, segmentos)

    assert ok_embeddings == embeddings
    assert ok_segmentos == segmentos


def test_remover_outliers_descarta_trecho_divergente():
    similares = [
        torch.tensor([1.0, 0.0]),
        torch.tensor([math.cos(0.05), math.sin(0.05)]),
        torch.tensor([math.cos(-0.05), math.sin(-0.05)]),
    ]
    outlier = torch.tensor([0.0, 1.0])  # ortogonal aos demais
    embeddings = similares + [outlier]
    segmentos = [{"idx": i} for i in range(4)]

    ok_embeddings, ok_segmentos = voice_service._remover_outliers(embeddings, segmentos)

    assert len(ok_embeddings) == 3
    assert {s["idx"] for s in ok_segmentos} == {0, 1, 2}


def test_remover_outliers_nunca_esvazia_tudo():
    # 3 vetores mutuamente ortogonais: nenhum se parece com os outros, mas o
    # fallback deve manter a lista original em vez de descartar tudo
    embeddings = [
        torch.tensor([1.0, 0.0, 0.0]),
        torch.tensor([0.0, 1.0, 0.0]),
        torch.tensor([0.0, 0.0, 1.0]),
    ]
    segmentos = [{"idx": i} for i in range(3)]

    ok_embeddings, ok_segmentos = voice_service._remover_outliers(embeddings, segmentos)

    assert len(ok_embeddings) == 3
    assert ok_segmentos == segmentos


# ---------------------------------------------------------------------------
# aplicar_biometria — campos separados, nunca concatenados; cluster preservado
# quando não identificado
# ---------------------------------------------------------------------------


def _diarizacao_um_cluster(duracoes) -> DiarizationResult:
    segmentos = []
    inicio = 0.0
    for i, duracao in enumerate(duracoes):
        segmentos.append(
            DiarizedSegment(
                id=i, cluster="SPEAKER_00", start=inicio, end=inicio + duracao, text=f"trecho {i}"
            )
        )
        inicio += duracao + 1.0
    return DiarizationResult(segments=segmentos)


def test_aplicar_biometria_identifica_com_campos_separados(monkeypatch):
    monkeypatch.setattr(voice_service, "extrair_embedding_segmento", lambda *a, **k: torch.tensor([1.0, 0.0]))
    monkeypatch.setattr(voice_service, "extrair_embedding_concatenado", lambda *a, **k: torch.tensor([1.0, 0.0]))

    diarizacao = _diarizacao_um_cluster([3.0, 3.0])
    banco = {"p1": torch.tensor([1.0, 0.0])}
    nomes = {"p1": "Leandro"}

    resultado = voice_service.aplicar_biometria("reuniao.wav", diarizacao, banco, nomes=nomes)

    assert len(resultado) == 2
    for segmento in resultado:
        assert segmento.cluster == "SPEAKER_00"
        assert segmento.participant_id == "p1"
        assert segmento.speaker == "Leandro"
        assert segmento.identified is True
        assert segmento.confidence > 0.99
        # nunca "Leandro (0.99)" — score jamais concatenado ao nome
        assert "(" not in segmento.speaker


def test_aplicar_biometria_nao_identificado_mantem_cluster_sem_associacao_posicional(monkeypatch):
    monkeypatch.setattr(voice_service, "extrair_embedding_segmento", lambda *a, **k: torch.tensor([0.0, 1.0]))
    monkeypatch.setattr(voice_service, "extrair_embedding_concatenado", lambda *a, **k: torch.tensor([0.0, 1.0]))

    diarizacao = _diarizacao_um_cluster([3.0])
    banco = {"p1": torch.tensor([1.0, 0.0])}  # ortogonal ao embedding do cluster
    nomes = {"p1": "Leandro"}

    resultado = voice_service.aplicar_biometria("reuniao.wav", diarizacao, banco, nomes=nomes)

    assert len(resultado) == 1
    segmento = resultado[0]
    assert segmento.cluster == "SPEAKER_00"
    assert segmento.participant_id is None
    assert segmento.speaker is None
    assert segmento.identified is False
    # confidence NUNCA vira None por rejeição — o sinal de identificação é o
    # campo `identified`, não a ausência de score. Aqui o embedding do
    # cluster é ortogonal ao único candidato do banco, então o score
    # (rejeitado) é ~0.0, mas continua exposto para calibrar os thresholds.
    assert segmento.confidence is not None
    assert segmento.confidence == pytest.approx(0.0, abs=1e-6)


def test_aplicar_biometria_sem_segmentos_longos_o_suficiente_nao_extrai_embedding(monkeypatch):
    def _falha_se_chamado(*args, **kwargs):
        raise AssertionError("não deveria extrair embedding sem candidatos válidos")

    monkeypatch.setattr(voice_service, "extrair_embedding_segmento", _falha_se_chamado)
    monkeypatch.setattr(voice_service, "extrair_embedding_concatenado", _falha_se_chamado)

    # segmentos mais curtos que duracao_min (1.5s default)
    diarizacao = _diarizacao_um_cluster([0.5, 0.8])

    resultado = voice_service.aplicar_biometria("reuniao.wav", diarizacao, banco={"p1": torch.tensor([1.0, 0.0])})

    assert all(not s.identified for s in resultado)
    assert all(s.cluster == "SPEAKER_00" for s in resultado)
    # sem candidato válido não há score real (nenhum embedding foi extraído);
    # o fallback 0.0 continua exposto (não None) — identified é o sinal.
    assert all(s.confidence == pytest.approx(0.0, abs=1e-6) for s in resultado)


def test_aplicar_biometria_expoe_score_mesmo_rejeitado_por_margem(monkeypatch):
    # dois embeddings no banco quase colados entre si e ambos próximos do
    # embedding do cluster: score alto, mas rejeitado por margem ambígua.
    monkeypatch.setattr(
        voice_service,
        "extrair_embedding_segmento",
        lambda *a, **k: torch.tensor([math.cos(0.0), math.sin(0.0)]),
    )
    monkeypatch.setattr(
        voice_service,
        "extrair_embedding_concatenado",
        lambda *a, **k: torch.tensor([math.cos(0.0), math.sin(0.0)]),
    )

    diarizacao = _diarizacao_um_cluster([3.0])
    banco = {
        "p1": torch.tensor([math.cos(0.01), math.sin(0.01)]),
        "p2": torch.tensor([math.cos(0.02), math.sin(0.02)]),
    }

    resultado = voice_service.aplicar_biometria("reuniao.wav", diarizacao, banco)

    segmento = resultado[0]
    assert segmento.identified is False
    assert segmento.participant_id is None
    # rejeitado por margem, mas o score (alto) continua exposto em confidence
    assert segmento.confidence > 0.99


def test_aplicar_biometria_sem_participant_id_speaker_fica_none_mesmo_sem_nomes(monkeypatch):
    monkeypatch.setattr(voice_service, "extrair_embedding_segmento", lambda *a, **k: torch.tensor([1.0, 0.0]))
    monkeypatch.setattr(voice_service, "extrair_embedding_concatenado", lambda *a, **k: torch.tensor([1.0, 0.0]))

    diarizacao = _diarizacao_um_cluster([3.0])
    banco = {"p1": torch.tensor([1.0, 0.0])}

    # nomes não informado -> mesmo identificado, 'speaker' fica None em vez de quebrar
    resultado = voice_service.aplicar_biometria("reuniao.wav", diarizacao, banco)

    assert resultado[0].participant_id == "p1"
    assert resultado[0].speaker is None
