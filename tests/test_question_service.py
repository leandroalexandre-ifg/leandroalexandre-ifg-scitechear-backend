import json

import pytest
from pydantic import ValidationError

from app.config import get_settings
from app.models.result import Segment
from app.services import question_service
from app.services.transcript_formatter import TranscriptFormatter


def _formatter():
    segmentos = [
        Segment(
            id="seg_0001",
            cluster="SPEAKER_00",
            participant_id="p1",
            speaker="Leandro",
            identified=True,
            confidence=0.9,
            start=0.0,
            end=2.0,
            text="Bom dia a todos.",
        ),
        Segment(
            id="seg_0002",
            cluster="SPEAKER_00",
            participant_id="p1",
            speaker="Leandro",
            identified=True,
            confidence=0.9,
            start=2.5,
            end=4.0,
            text="Qual é o prazo?",
        ),
    ]
    return TranscriptFormatter(segmentos)


# ---------------------------------------------------------------------------
# _extrair_json
# ---------------------------------------------------------------------------


def test_extrair_json_direto():
    assert question_service._extrair_json('{"a": 1}') == {"a": 1}


def test_extrair_json_tolera_cerca_markdown():
    texto = '```json\n{"a": 1}\n```'
    assert question_service._extrair_json(texto) == {"a": 1}


def test_extrair_json_recupera_de_texto_com_ruido_ao_redor():
    texto = 'Aqui está: {"a": 1} — obrigado.'
    assert question_service._extrair_json(texto) == {"a": 1}


def test_extrair_json_invalido_levanta_erro():
    with pytest.raises(ValueError):
        question_service._extrair_json("isso não é json")


# ---------------------------------------------------------------------------
# extract_explicit_questions — parser/validador do JSON explícito
# ---------------------------------------------------------------------------


def test_extract_explicit_questions_resolve_via_formatter_nao_via_llm(monkeypatch):
    resposta = json.dumps(
        {
            "perguntas": [
                {
                    "id": "P1",
                    "pergunta": "Qual é o prazo?",
                    "falante": "Leandro",
                    "linha_transcricao": 2,
                    "segmentos_anteriores": ["1 -> seg_0001 -> [Leandro]: Bom dia a todos."],
                }
            ],
            "total_perguntas": 1,
        }
    )
    monkeypatch.setattr(question_service, "_chamar_ollama", lambda prompt: resposta)

    perguntas = question_service.extract_explicit_questions(_formatter())

    assert len(perguntas) == 1
    pergunta = perguntas[0]
    assert pergunta.type.value == "explicit"
    assert pergunta.text == "Qual é o prazo?"  # literal
    assert pergunta.participant_id == "p1"
    assert pergunta.speaker == "Leandro"
    assert pergunta.time == 2.5
    assert pergunta.source_segment_ids == ["seg_0002"]


def test_extract_explicit_questions_linha_fora_do_range_fica_com_campos_nulos(monkeypatch):
    resposta = json.dumps(
        {
            "perguntas": [
                {
                    "id": "P1",
                    "pergunta": "Pergunta com linha inválida?",
                    "falante": "Leandro",
                    "linha_transcricao": 999,
                    "segmentos_anteriores": [],
                }
            ],
            "total_perguntas": 1,
        }
    )
    monkeypatch.setattr(question_service, "_chamar_ollama", lambda prompt: resposta)

    perguntas = question_service.extract_explicit_questions(_formatter())

    assert perguntas[0].participant_id is None
    assert perguntas[0].speaker is None
    assert perguntas[0].time is None
    assert perguntas[0].source_segment_ids == []


def test_extract_explicit_questions_json_invalido_levanta_erro(monkeypatch):
    monkeypatch.setattr(question_service, "_chamar_ollama", lambda prompt: "não é json")

    with pytest.raises(ValueError):
        question_service.extract_explicit_questions(_formatter())


def test_extract_explicit_questions_schema_invalido_levanta_erro(monkeypatch):
    resposta = json.dumps({"perguntas": [{"id": "P1"}], "total_perguntas": 1})  # faltam campos
    monkeypatch.setattr(question_service, "_chamar_ollama", lambda prompt: resposta)

    with pytest.raises(ValidationError):
        question_service.extract_explicit_questions(_formatter())


# ---------------------------------------------------------------------------
# extract_implicit_questions — campos opcionais (speaker/time nunca inventados)
# e validação obrigatória de linhas_evidencia contra a transcrição real
# ---------------------------------------------------------------------------


def test_extract_implicit_questions_speaker_e_time_ficam_none(monkeypatch):
    resposta = json.dumps(
        {
            "perguntas_implicitas": [
                {"id": "I1", "pergunta": "Quais critérios validam a qualidade?", "linhas_evidencia": [1]},
                {"id": "I2", "pergunta": "Quais riscos técnicos existem?", "linhas_evidencia": [2]},
            ],
            "total_perguntas": 2,
        }
    )
    monkeypatch.setattr(question_service, "_chamar_ollama", lambda prompt: resposta)

    perguntas = question_service.extract_implicit_questions(_formatter(), summary="resumo qualquer")

    assert len(perguntas) == 2
    for pergunta in perguntas:
        assert pergunta.type.value == "implicit"
        assert pergunta.participant_id is None
        assert pergunta.speaker is None
        assert pergunta.time is None


def test_extract_implicit_questions_schema_invalido_levanta_erro(monkeypatch):
    resposta = json.dumps({"perguntas": [{"id": "I1", "pergunta": "x"}]})  # chave errada
    monkeypatch.setattr(question_service, "_chamar_ollama", lambda prompt: resposta)

    with pytest.raises(ValidationError):
        question_service.extract_implicit_questions(_formatter(), summary="resumo")


def test_extract_implicit_questions_evidencia_valida_preenche_source_segment_ids(monkeypatch):
    resposta = json.dumps(
        {
            "perguntas_implicitas": [
                {"id": "I1", "pergunta": "Pergunta com lastro real?", "linhas_evidencia": [1, 2]},
            ],
            "total_perguntas": 1,
        }
    )
    monkeypatch.setattr(question_service, "_chamar_ollama", lambda prompt: resposta)

    perguntas = question_service.extract_implicit_questions(_formatter(), summary="resumo")

    assert len(perguntas) == 1
    assert perguntas[0].source_segment_ids == ["seg_0001", "seg_0002"]


def test_extract_implicit_questions_sem_linhas_evidencia_e_descartada(monkeypatch):
    resposta = json.dumps(
        {
            "perguntas_implicitas": [
                {"id": "I1", "pergunta": "Pergunta sem nenhuma evidência citada?", "linhas_evidencia": []},
            ],
            "total_perguntas": 1,
        }
    )
    monkeypatch.setattr(question_service, "_chamar_ollama", lambda prompt: resposta)

    perguntas = question_service.extract_implicit_questions(_formatter(), summary="resumo")

    assert perguntas == []


def test_extract_implicit_questions_maioria_das_linhas_invalida_descarta_pergunta_inteira(monkeypatch):
    # 1 linha real (2) e 1 fora do range (999) -> 50%, não é maioria estrita -> descarta tudo.
    resposta = json.dumps(
        {
            "perguntas_implicitas": [
                {"id": "I1", "pergunta": "Pergunta majoritariamente inventada?", "linhas_evidencia": [2, 999]},
            ],
            "total_perguntas": 1,
        }
    )
    monkeypatch.setattr(question_service, "_chamar_ollama", lambda prompt: resposta)

    perguntas = question_service.extract_implicit_questions(_formatter(), summary="resumo")

    assert perguntas == []


def test_extract_implicit_questions_maioria_das_linhas_valida_mantem_so_as_validas(monkeypatch):
    # 2 linhas reais (1, 2) e 1 fora do range (999) -> maioria válida -> mantém, mas só com as reais.
    resposta = json.dumps(
        {
            "perguntas_implicitas": [
                {"id": "I1", "pergunta": "Pergunta com erro de contagem pontual?", "linhas_evidencia": [1, 2, 999]},
            ],
            "total_perguntas": 1,
        }
    )
    monkeypatch.setattr(question_service, "_chamar_ollama", lambda prompt: resposta)

    perguntas = question_service.extract_implicit_questions(_formatter(), summary="resumo")

    assert len(perguntas) == 1
    assert perguntas[0].source_segment_ids == ["seg_0001", "seg_0002"]


def test_extract_implicit_questions_regressao_descarta_maioria_alucinada(monkeypatch):
    """Espelha o incidente real: poucas perguntas com evidência real devem
    sobreviver, o resto (roteiro genérico sem lastro) deve ser descartado."""
    perguntas_geradas = [
        {"id": "I1", "pergunta": "Pergunta com lastro real (linha 1)?", "linhas_evidencia": [1]},
        {"id": "I2", "pergunta": "Pergunta com lastro real (linha 2)?", "linhas_evidencia": [2]},
    ] + [
        {"id": f"I{i}", "pergunta": f"Pergunta de roteiro genérico {i}?", "linhas_evidencia": [900 + i]}
        for i in range(3, 20)
    ]
    resposta = json.dumps({"perguntas_implicitas": perguntas_geradas, "total_perguntas": len(perguntas_geradas)})
    monkeypatch.setattr(question_service, "_chamar_ollama", lambda prompt: resposta)

    perguntas = question_service.extract_implicit_questions(_formatter(), summary="resumo")

    assert len(perguntas) == 2
    assert {p.text for p in perguntas} == {
        "Pergunta com lastro real (linha 1)?",
        "Pergunta com lastro real (linha 2)?",
    }


# ---------------------------------------------------------------------------
# summarize_meeting — texto interno, sem parsing
# ---------------------------------------------------------------------------


def test_summarize_meeting_retorna_texto_bruto(monkeypatch):
    monkeypatch.setattr(question_service, "_chamar_ollama", lambda prompt: "1. Contexto\nObjetivo: ...")

    resumo = question_service.summarize_meeting(_formatter())

    assert resumo == "1. Contexto\nObjetivo: ..."


# ---------------------------------------------------------------------------
# gerar_perguntas — orquestração e feature flag de refinamento
# ---------------------------------------------------------------------------


def test_gerar_perguntas_nao_chama_refinamento_por_padrao(monkeypatch):
    monkeypatch.setattr(question_service, "extract_explicit_questions", lambda f: ["explicita"])
    monkeypatch.setattr(question_service, "summarize_meeting", lambda f: "resumo")
    monkeypatch.setattr(question_service, "extract_implicit_questions", lambda f, s: ["implicita"])

    def _falha_se_chamado(*args, **kwargs):
        raise AssertionError("refinamento não deveria ser chamado com a flag desativada")

    monkeypatch.setattr(question_service, "refine_implicit_questions", _falha_se_chamado)

    resultado = question_service.gerar_perguntas(_formatter())

    assert resultado == ["explicita", "implicita"]


def test_gerar_perguntas_chama_refinamento_quando_flag_ativa(monkeypatch):
    monkeypatch.setenv("ENABLE_IMPLICIT_REFINEMENT", "true")
    get_settings.cache_clear()
    try:
        monkeypatch.setattr(question_service, "extract_explicit_questions", lambda f: ["explicita"])
        monkeypatch.setattr(question_service, "summarize_meeting", lambda f: "resumo")
        monkeypatch.setattr(question_service, "extract_implicit_questions", lambda f, s: ["implicita_bruta"])
        monkeypatch.setattr(question_service, "refine_implicit_questions", lambda qs, f: ["implicita_refinada"])

        resultado = question_service.gerar_perguntas(_formatter())

        assert resultado == ["explicita", "implicita_refinada"]
    finally:
        get_settings.cache_clear()


# ---------------------------------------------------------------------------
# Prompts existem e carregam
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "nome_arquivo",
    [
        question_service.EXPLICIT_QUESTIONS_PROMPT,
        question_service.MEETING_SUMMARY_PROMPT,
        question_service.IMPLICIT_QUESTIONS_PROMPT,
        question_service.IMPLICIT_REFINER_PROMPT,
    ],
)
def test_prompt_carrega_e_nao_esta_vazio(nome_arquivo):
    conteudo = question_service._carregar_prompt(nome_arquivo)
    assert conteudo.strip()
