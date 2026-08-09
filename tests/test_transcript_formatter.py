from app.models.result import Segment
from app.services.transcript_formatter import TranscriptFormatter


def _segmentos():
    return [
        Segment(
            id="seg_0001",
            cluster="SPEAKER_00",
            participant_id="p1",
            speaker="Leandro",
            identified=True,
            confidence=0.82,
            start=0.0,
            end=4.2,
            text="Bom dia.",
        ),
        Segment(
            id="seg_0002",
            cluster="SPEAKER_01",
            participant_id=None,
            speaker=None,
            identified=False,
            confidence=0.1,
            start=4.2,
            end=7.8,
            text="Tudo bem?",
        ),
        Segment(
            id="seg_0003",
            cluster="SPEAKER_00",
            participant_id="p1",
            speaker="Leandro",
            identified=True,
            confidence=0.9,
            start=8.0,
            end=10.0,
            text="Vamos iniciar.",
        ),
    ]


def test_render_usa_nome_quando_identificado_e_cluster_quando_nao():
    formatter = TranscriptFormatter(_segmentos())

    esperado = (
        "1 -> seg_0001 -> [Leandro]: Bom dia.\n"
        "2 -> seg_0002 -> [SPEAKER_01]: Tudo bem?\n"
        "3 -> seg_0003 -> [Leandro]: Vamos iniciar."
    )
    assert formatter.render() == esperado


def test_resolve_linha_identificada_traz_participant_id_e_time():
    formatter = TranscriptFormatter(_segmentos())

    resolvida = formatter.resolve(1)

    assert resolvida is not None
    assert resolvida.participant_id == "p1"
    assert resolvida.speaker == "Leandro"
    assert resolvida.time == 0.0
    assert resolvida.source_segment_ids == ["seg_0001"]


def test_resolve_linha_nao_identificada_traz_participant_id_none():
    formatter = TranscriptFormatter(_segmentos())

    resolvida = formatter.resolve(2)

    assert resolvida is not None
    assert resolvida.participant_id is None
    assert resolvida.speaker is None
    assert resolvida.time == 4.2
    assert resolvida.source_segment_ids == ["seg_0002"]


def test_resolve_linha_fora_do_range_retorna_none():
    formatter = TranscriptFormatter(_segmentos())

    assert formatter.resolve(0) is None
    assert formatter.resolve(999) is None


def test_get_line_devolve_a_linha_formatada():
    formatter = TranscriptFormatter(_segmentos())

    linha = formatter.get_line(3)

    assert linha is not None
    assert linha.segment_id == "seg_0003"
    assert linha.label == "Leandro"
    assert linha.text == "Vamos iniciar."
