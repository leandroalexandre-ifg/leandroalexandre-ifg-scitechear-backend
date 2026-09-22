import json
import logging

import pytest
from pydantic import ValidationError

from app.config import get_settings
from app.models.result import Segment
from app.services import question_service
from app.services.transcript_formatter import TranscriptFormatter


# Sumário mínimo que atravessa o filtro estrutural intacto ("Contexto" é
# seção de texto livre, preservada). Os testes de parsing de implícitas não
# são sobre o conteúdo do sumário: precisam de um insumo VÁLIDO (desde o
# filtro, um texto qualquer não é mais aceito — ver summary_filter) e de um
# marcador rastreável dentro do prompt montado.
MARCADOR_SUMARIO = "MARCADOR-DO-SUMARIO-NO-PROMPT"
SUMARIO_MINIMO = f"Contexto\n\nObjetivo da reuni\u00e3o:  \n{MARCADOR_SUMARIO}.\n"


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
    monkeypatch.setattr(question_service, "_chamar_ollama", lambda prompt, **kwargs: resposta)

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
    monkeypatch.setattr(question_service, "_chamar_ollama", lambda prompt, **kwargs: resposta)

    perguntas = question_service.extract_explicit_questions(_formatter())

    assert perguntas[0].participant_id is None
    assert perguntas[0].speaker is None
    assert perguntas[0].time is None
    assert perguntas[0].source_segment_ids == []


def test_extract_explicit_questions_json_invalido_levanta_erro(monkeypatch):
    monkeypatch.setattr(question_service, "_chamar_ollama", lambda prompt, **kwargs: "não é json")

    with pytest.raises(ValueError):
        question_service.extract_explicit_questions(_formatter())


def test_extract_explicit_questions_schema_invalido_levanta_erro(monkeypatch):
    resposta = json.dumps({"perguntas": [{"id": "P1"}], "total_perguntas": 1})  # faltam campos
    monkeypatch.setattr(question_service, "_chamar_ollama", lambda prompt, **kwargs: resposta)

    with pytest.raises(ValidationError):
        question_service.extract_explicit_questions(_formatter())


def test_extract_explicit_questions_mantem_think_ligado(monkeypatch):
    """think=False foi TESTADO para extract_explicit_questions e revertido:
    comparação antes/depois com a mesma transcrição real (docs/PERFORMANCE.md)
    mostrou diferença de CONTEÚDO (não só velocidade) — perdeu uma pergunta
    genuína e ganhou uma frase que não terminava em "?". Este teste trava que
    a chamada continua com o default think=True até haver mitigação
    validada. Não "consertar" trocando para False sem repetir a validação."""
    resposta = json.dumps({"perguntas": [], "total_perguntas": 0})
    chamadas = []

    def fake_chamar_ollama(prompt, contexto=None, think=True):
        chamadas.append({"contexto": contexto, "think": think})
        return resposta

    monkeypatch.setattr(question_service, "_chamar_ollama", fake_chamar_ollama)

    question_service.extract_explicit_questions(_formatter())

    assert len(chamadas) == 1
    assert chamadas[0]["contexto"] == "extract_explicit_questions"
    assert chamadas[0]["think"] is True


def test_summarize_e_implicitas_continuam_com_think_ligado_por_padrao(monkeypatch):
    """Nenhuma chamada ao Ollama teve think desligado nesta rodada de
    calibração — sumarização e implícitas (mesmo desligadas por
    ENABLE_IMPLICIT_QUESTIONS) continuam no default think=True."""
    chamadas = []

    def fake_chamar_ollama(prompt, contexto=None, think=True):
        chamadas.append({"contexto": contexto, "think": think})
        return json.dumps({"perguntas_implicitas": [], "total_perguntas": 0})

    monkeypatch.setattr(question_service, "_chamar_ollama", fake_chamar_ollama)

    question_service.summarize_meeting(_formatter())
    question_service.extract_implicit_questions(_formatter(), summary=SUMARIO_MINIMO)

    assert len(chamadas) == 2
    assert all(c["think"] is True for c in chamadas)
    assert {c["contexto"] for c in chamadas} == {"summarize_meeting", "extract_implicit_questions"}


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
    monkeypatch.setattr(question_service, "_chamar_ollama", lambda prompt, **kwargs: resposta)

    perguntas = question_service.extract_implicit_questions(_formatter(), summary=SUMARIO_MINIMO)

    assert len(perguntas) == 2
    for pergunta in perguntas:
        assert pergunta.type.value == "implicit"
        assert pergunta.participant_id is None
        assert pergunta.speaker is None
        assert pergunta.time is None


def test_extract_implicit_questions_schema_invalido_levanta_erro(monkeypatch):
    resposta = json.dumps({"perguntas": [{"id": "I1", "pergunta": "x"}]})  # chave errada
    monkeypatch.setattr(question_service, "_chamar_ollama", lambda prompt, **kwargs: resposta)

    with pytest.raises(ValidationError):
        question_service.extract_implicit_questions(_formatter(), summary=SUMARIO_MINIMO)


def test_extract_implicit_questions_evidencia_valida_preenche_source_segment_ids(monkeypatch):
    resposta = json.dumps(
        {
            "perguntas_implicitas": [
                {"id": "I1", "pergunta": "Pergunta com lastro real?", "linhas_evidencia": [1, 2]},
            ],
            "total_perguntas": 1,
        }
    )
    monkeypatch.setattr(question_service, "_chamar_ollama", lambda prompt, **kwargs: resposta)

    perguntas = question_service.extract_implicit_questions(_formatter(), summary=SUMARIO_MINIMO)

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
    monkeypatch.setattr(question_service, "_chamar_ollama", lambda prompt, **kwargs: resposta)

    perguntas = question_service.extract_implicit_questions(_formatter(), summary=SUMARIO_MINIMO)

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
    monkeypatch.setattr(question_service, "_chamar_ollama", lambda prompt, **kwargs: resposta)

    perguntas = question_service.extract_implicit_questions(_formatter(), summary=SUMARIO_MINIMO)

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
    monkeypatch.setattr(question_service, "_chamar_ollama", lambda prompt, **kwargs: resposta)

    perguntas = question_service.extract_implicit_questions(_formatter(), summary=SUMARIO_MINIMO)

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
    monkeypatch.setattr(question_service, "_chamar_ollama", lambda prompt, **kwargs: resposta)

    perguntas = question_service.extract_implicit_questions(_formatter(), summary=SUMARIO_MINIMO)

    assert len(perguntas) == 2
    assert {p.text for p in perguntas} == {
        "Pergunta com lastro real (linha 1)?",
        "Pergunta com lastro real (linha 2)?",
    }


# ---------------------------------------------------------------------------
# summarize_meeting — texto interno, sem parsing
# ---------------------------------------------------------------------------


def test_summarize_meeting_retorna_texto_bruto(monkeypatch):
    monkeypatch.setattr(question_service, "_chamar_ollama", lambda prompt, **kwargs: "1. Contexto\nObjetivo: ...")

    resumo = question_service.summarize_meeting(_formatter())

    assert resumo == "1. Contexto\nObjetivo: ..."


# ---------------------------------------------------------------------------
# gerar_perguntas — orquestração e feature flag de refinamento
# ---------------------------------------------------------------------------


def test_gerar_perguntas_nao_chama_refinamento_por_padrao(monkeypatch):
    monkeypatch.setattr(question_service, "extract_explicit_questions", lambda f: ["explicita"])
    monkeypatch.setattr(question_service, "summarize_meeting", lambda f: SUMARIO_MINIMO)
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
        monkeypatch.setattr(question_service, "summarize_meeting", lambda f: SUMARIO_MINIMO)
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


def test_prompt_de_explicitas_proibe_o_rotulo_do_falante_no_campo_pergunta():
    """O prefixo `[Nome]: `/`[SPEAKER_XX]: ` vazando no campo `text` foi
    diagnosticado no E2E da Fase 8 (docs/E2E_FASE8.md): acontecia só quando o
    falante NÃO era identificado e o rótulo da linha era `[SPEAKER_00]` em vez
    de um nome próprio. O v5 corrigiu por prompt — o serviço continua
    repassando `item.pergunta` literalmente, sem cortar string nenhuma.

    Este teste trava as duas partes da correção. Não "simplificar" removendo o
    exemplo com rótulo genérico: era exatamente o caso que faltava no v4."""
    prompt = json.loads(
        question_service._carregar_prompt(question_service.EXPLICIT_QUESTIONS_PROMPT)
    )

    regras = " ".join(prompt["regras"])
    assert "rótulo do falante" in regras and "[SPEAKER_00]" in regras

    exemplos = prompt["exemplos_few_shot"]
    com_rotulo_generico = [
        e for e in exemplos if any("[SPEAKER_" in linha for linha in e["entrada"])
    ]
    assert com_rotulo_generico, "faltou exemplo few-shot com falante não identificado"
    for exemplo in exemplos:
        for pergunta in exemplo["saida"]["perguntas"]:
            assert not pergunta["pergunta"].startswith("["), (
                f"exemplo few-shot ensina o prefixo errado: {pergunta['pergunta']}"
            )


def test_extract_explicit_questions_nao_corrige_o_texto_devolvido_pelo_llm(monkeypatch):
    """Contrapeso do teste acima: a correção do prefixo foi por PROMPT, não
    por saneamento no código. Se alguém tentar "ajudar" cortando o prefixo em
    Python, este teste quebra — a regra do projeto é repassar o texto do LLM
    literalmente, inclusive quando ele vem errado."""
    resposta = json.dumps({
        "perguntas": [{
            "id": "P1",
            "pergunta": "[SPEAKER_00]: Subiu?",
            "falante": "SPEAKER_00",
            "linha_transcricao": 1,
            "segmentos_anteriores": [],
        }],
        "total_perguntas": 1,
    })
    monkeypatch.setattr(
        question_service, "_chamar_ollama", lambda *a, **k: resposta
    )

    perguntas = question_service.extract_explicit_questions(_formatter())

    assert perguntas[0].text == "[SPEAKER_00]: Subiu?"


# ---------------------------------------------------------------------------
# extract_implicit_questions — prompt v6 (IMPLICIT_QUESTIONS_PROMPT_VERSION)
#
# O v6 é texto do usuário e pede um formato incompatível com o v4: lista
# numerada de texto puro, sem JSON e sem `linhas_evidencia`. Estes testes
# travam as quatro guardas acordadas para esse caminho — parser estrito,
# sentinela "Não possui", campos opcionais nulos e teto de 15 sem truncar —
# e, principalmente, que o DEFAULT continua sendo o v4.
# ---------------------------------------------------------------------------


def _com_versao_implicitas(monkeypatch, versao):
    monkeypatch.setenv("IMPLICIT_QUESTIONS_PROMPT_VERSION", versao)
    get_settings.cache_clear()


def _resposta_fixa(monkeypatch, texto, capturar=None):
    def _fake(prompt, **kwargs):
        if capturar is not None:
            capturar.append(prompt)
        return texto

    monkeypatch.setattr(question_service, "_chamar_ollama", _fake)


def test_versao_default_das_implicitas_continua_v4(monkeypatch):
    """Sem a variável definida, nada muda: o caminho JSON + evidência do v4
    é o que roda. Se este teste quebrar, o default virou v6 por acidente e a
    validação anti-confabulação saiu de produção sem ninguém decidir isso."""
    monkeypatch.delenv("IMPLICIT_QUESTIONS_PROMPT_VERSION", raising=False)
    get_settings.cache_clear()
    try:
        assert get_settings().implicit_questions_prompt_version == "v4"

        # Uma resposta em lista numerada (formato do v6) precisa FALHAR aqui,
        # provando que o parser do v4 continua no caminho default.
        _resposta_fixa(monkeypatch, "1. Pergunta em lista numerada?")
        with pytest.raises(ValueError):
            question_service.extract_implicit_questions(_formatter(), summary=SUMARIO_MINIMO)
    finally:
        get_settings.cache_clear()


def test_v6_parser_estrito_ignora_preambulo_e_posfacio(monkeypatch):
    """Guarda 1: só linhas `N. ` / `N) ` viram pergunta. Preâmbulo do modelo,
    cerca de markdown, linha em branco e comentário final são descartados —
    e o texto da pergunta vai literal, sem reescrita."""
    _com_versao_implicitas(monkeypatch, "v6")
    try:
        _resposta_fixa(
            monkeypatch,
            "Aqui estão as perguntas implícitas identificadas:\n"
            "```\n"
            "1. Como será validado o prazo de entrega sem critério definido?\n"
            "2) Que impacto a ausência de dados próprios terá no fine-tuning?\n"
            "3.Sem espaço depois do ponto não é item da lista\n"
            "```\n"
            "Espero que ajude.",
        )

        perguntas = question_service.extract_implicit_questions(_formatter(), summary=SUMARIO_MINIMO)

        assert [p.text for p in perguntas] == [
            "Como será validado o prazo de entrega sem critério definido?",
            "Que impacto a ausência de dados próprios terá no fine-tuning?",
        ]
        assert [p.id for p in perguntas] == ["I1", "I2"]
    finally:
        get_settings.cache_clear()


@pytest.mark.parametrize(
    "resposta",
    [
        "Não possui",
        "não possui",
        "NÃO POSSUI.",
        "  Nao possui  ",
        "1. Não possui",
    ],
)
def test_v6_sentinela_nao_possui_da_zero_perguntas(monkeypatch, resposta):
    """Guarda 2: "Não possui" é a saída de lista vazia do próprio prompt —
    inclusive quando o modelo a numera. Nunca pode virar uma pergunta."""
    _com_versao_implicitas(monkeypatch, "v6")
    try:
        _resposta_fixa(monkeypatch, resposta)

        assert question_service.extract_implicit_questions(_formatter(), summary=SUMARIO_MINIMO) == []
    finally:
        get_settings.cache_clear()


def test_v6_resposta_fora_do_formato_levanta_erro_em_vez_de_lista_vazia(monkeypatch):
    """Sem lista numerada E sem o sentinela, o modelo não respondeu no formato
    pedido. Isso é erro real do backend (regra inviolável nº 5) e não pode ser
    confundido com "esta reunião não tem perguntas implícitas"."""
    _com_versao_implicitas(monkeypatch, "v6")
    try:
        _resposta_fixa(monkeypatch, "Não identifiquei nada relevante na reunião.")

        with pytest.raises(ValueError, match="não contém lista numerada"):
            question_service.extract_implicit_questions(_formatter(), summary=SUMARIO_MINIMO)
    finally:
        get_settings.cache_clear()


def test_v6_campos_opcionais_nulos_e_source_segment_ids_vazio(monkeypatch):
    """Guarda 3: o v6 não pede evidência, então não há o que resolver —
    `source_segment_ids` fica honestamente vazio em vez de ancorado por
    similaridade, e participant_id/speaker/time seguem null como sempre."""
    _com_versao_implicitas(monkeypatch, "v6")
    try:
        _resposta_fixa(monkeypatch, "1. Qual critério de aceite fica pendente?")

        pergunta = question_service.extract_implicit_questions(_formatter(), summary=SUMARIO_MINIMO)[0]

        assert pergunta.type.value == "implicit"
        assert pergunta.participant_id is None
        assert pergunta.speaker is None
        assert pergunta.time is None
        assert pergunta.source_segment_ids == []
    finally:
        get_settings.cache_clear()


def test_v6_acima_do_teto_de_15_loga_aviso_e_nao_trunca(monkeypatch, caplog):
    """Guarda 4: o teto de 15 do prompt é observado, não aplicado. Truncar
    esconderia justamente o comportamento do modelo que o comparativo v4 × v6
    precisa medir."""
    _com_versao_implicitas(monkeypatch, "v6")
    try:
        _resposta_fixa(
            monkeypatch,
            "\n".join(f"{i}. Pergunta número {i}?" for i in range(1, 19)),
        )

        with caplog.at_level(logging.WARNING, logger=question_service.logger.name):
            perguntas = question_service.extract_implicit_questions(_formatter(), summary=SUMARIO_MINIMO)

        assert len(perguntas) == 18
        assert [p.id for p in perguntas] == [f"I{i}" for i in range(1, 19)]
        assert any("acima do teto" in r.getMessage() for r in caplog.records)
    finally:
        get_settings.cache_clear()


def test_v6_monta_transcricao_direto_apos_o_banner_e_sumario_no_fim(monkeypatch):
    """D2-b: o texto do prompt v6 termina no banner ###REUNIÃO ABAIXO###, então
    é a TRANSCRIÇÃO que tem de vir logo depois — no v4 a ordem é a inversa
    (sumário primeiro). O sumário entra por último, sob um cabeçalho de cola
    que vive no código, não no arquivo de prompt (que é texto do usuário e não
    pode ser editado)."""
    _com_versao_implicitas(monkeypatch, "v6")
    try:
        prompts = []
        _resposta_fixa(monkeypatch, "1. Pergunta qualquer?", capturar=prompts)
        formatter = _formatter()

        question_service.extract_implicit_questions(formatter, summary=SUMARIO_MINIMO)

        prompt_final = prompts[0]
        texto_prompt = question_service._carregar_prompt(
            question_service.IMPLICIT_QUESTIONS_PROMPT_V6
        )
        transcricao = formatter.render()

        assert prompt_final.startswith(texto_prompt)
        posicao_banner = prompt_final.index("REUNIÃO ABAIXO")
        posicao_transcricao = prompt_final.index(transcricao)
        posicao_cabecalho = prompt_final.index(question_service.IMPLICIT_SUMMARY_HEADER)
        posicao_sumario = prompt_final.index(MARCADOR_SUMARIO)

        assert posicao_banner < posicao_transcricao < posicao_cabecalho < posicao_sumario
        # Nada entre o fim do texto do prompt (que termina no banner) e o
        # começo da transcrição além de espaço em branco.
        assert prompt_final[len(texto_prompt) : posicao_transcricao].strip() == ""
    finally:
        get_settings.cache_clear()


def test_prompt_v6_foi_colado_sem_alteracao_e_sem_pedir_evidencia():
    """O arquivo do v6 é texto do usuário. Trava o que não pode mudar: o
    banner final (de que depende a montagem), o sentinela de lista vazia, o
    teto de 15 — e a ausência de qualquer pedido de evidência estruturada,
    que é a razão de o caminho v6 não ter validação automática."""
    conteudo = question_service._carregar_prompt(question_service.IMPLICIT_QUESTIONS_PROMPT_V6)

    assert conteudo.rstrip().endswith("####################################################")
    assert "REUNIÃO ABAIXO" in conteudo
    assert "Não possui" in conteudo
    assert "Não ultrapasse 15 perguntas" in conteudo
    assert "linhas_evidencia" not in conteudo
    assert "JSON" not in conteudo


# ---------------------------------------------------------------------------
# Ligação do filtro estrutural do sumário (app/services/summary_filter.py).
# Aqui não se testa o filtro em si — isso é tests/test_summary_filter.py —,
# e sim que ele está DE FATO no caminho que monta o prompt das implícitas.
# ---------------------------------------------------------------------------

_SUMARIO_COM_INFERENCIA = (
    "Contexto\n\n"
    "Objetivo da reunião:  \n"
    "PRESERVA-ESTE-TRECHO.\n\n"
    "Conteúdo explícito\n\n"
    "Prazos\n\n"
    "- id: PR1\n"
    "  Resumo: Não há prazo explícito mencionado.\n\n"
    "Conhecimento implícito\n\n"
    "Dependências implícitas\n\n"
    "- id: DI1\n"
    "  Resumo: DESCARTA-ESTA-INFERENCIA.\n"
)


def test_extract_implicit_questions_filtra_o_sumario_antes_de_montar_o_prompt(monkeypatch):
    """A inferência do sumarizador e os placeholders de ausência não podem
    chegar ao gerador de perguntas — é a origem rastreada de 4 das 5 premissas
    sem lastro do comparativo v4 × v6."""
    monkeypatch.delenv("ENABLE_SUMMARY_FILTER", raising=False)
    get_settings.cache_clear()
    try:
        prompts = []
        _resposta_fixa(
            monkeypatch,
            json.dumps({"perguntas_implicitas": [], "total_perguntas": 0}),
            capturar=prompts,
        )

        question_service.extract_implicit_questions(
            _formatter(), summary=_SUMARIO_COM_INFERENCIA
        )

        assert "PRESERVA-ESTE-TRECHO" in prompts[0]
        assert "DESCARTA-ESTA-INFERENCIA" not in prompts[0]
        assert "Não há prazo explícito" not in prompts[0]
    finally:
        get_settings.cache_clear()


def test_enable_summary_filter_false_entrega_o_sumario_cru(monkeypatch):
    """O desligamento existe para medir com e sem filtro na mesma execução;
    se ele parar de desligar, a comparação deixa de ser possível."""
    monkeypatch.setenv("ENABLE_SUMMARY_FILTER", "false")
    get_settings.cache_clear()
    try:
        prompts = []
        _resposta_fixa(
            monkeypatch,
            json.dumps({"perguntas_implicitas": [], "total_perguntas": 0}),
            capturar=prompts,
        )

        question_service.extract_implicit_questions(
            _formatter(), summary=_SUMARIO_COM_INFERENCIA
        )

        assert "DESCARTA-ESTA-INFERENCIA" in prompts[0]
    finally:
        get_settings.cache_clear()


def test_filtro_do_sumario_vale_tambem_para_o_v6(monkeypatch):
    """A contaminação é do insumo, não do prompt: os dois caminhos recebem o
    sumário saneado."""
    _com_versao_implicitas(monkeypatch, "v6")
    try:
        prompts = []
        _resposta_fixa(monkeypatch, "Não possui", capturar=prompts)

        question_service.extract_implicit_questions(
            _formatter(), summary=_SUMARIO_COM_INFERENCIA
        )

        assert "DESCARTA-ESTA-INFERENCIA" not in prompts[0]
    finally:
        get_settings.cache_clear()


def test_filtro_ligado_por_padrao(monkeypatch):
    """Se este teste quebrar, o insumo contaminado voltou a produção sem
    ninguém decidir isso."""
    monkeypatch.delenv("ENABLE_SUMMARY_FILTER", raising=False)
    get_settings.cache_clear()
    try:
        assert get_settings().enable_summary_filter is True
    finally:
        get_settings.cache_clear()
