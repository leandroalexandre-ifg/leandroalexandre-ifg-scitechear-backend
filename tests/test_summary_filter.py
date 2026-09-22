"""Filtro estrutural do sumário (app/services/summary_filter.py).

Os casos de contrato rodam contra os quatro sumários REAIS gravados em
docs/repro/implicitas-v4-v6/ durante o comparativo v4 × v6 — mesmo material em
que a contaminação foi diagnosticada, sem GPU e sem Ollama. Os unitários usam
fixtures mínimas para as bordas de formato.
"""
import re
from pathlib import Path

import pytest

from app.services.summary_filter import filtrar_sumario

REPRO = Path(__file__).resolve().parents[1] / "docs" / "repro" / "implicitas-v4-v6"
SUMARIOS_REAIS = sorted(REPRO.glob("*_sumario.txt"))
RE_ELEMENTO = re.compile(r"^\s*-\s*id:\s*(\S+)", re.M)


def _ler(job: str) -> str:
    return (REPRO / f"{job}_sumario.txt").read_text(encoding="utf-8")


# --------------------------------------------------------------------------
# Contrato contra os sumários reais
# --------------------------------------------------------------------------


def test_o_corpus_do_comparativo_esta_no_repositorio():
    """Guarda-chuva: se os artefatos sumirem, os testes abaixo viram vácuo."""
    assert len(SUMARIOS_REAIS) == 4


@pytest.mark.parametrize("caminho", SUMARIOS_REAIS, ids=lambda p: p.name.split("_")[0])
def test_secoes_de_inferencia_somem_do_sumario_real(caminho):
    filtrado = filtrar_sumario(caminho.read_text(encoding="utf-8"))
    assert "Conhecimento implícito" not in filtrado
    assert "Lacunas" not in filtrado


@pytest.mark.parametrize("caminho", SUMARIOS_REAIS, ids=lambda p: p.name.split("_")[0])
def test_nenhum_elemento_de_ausencia_sobrevive_no_sumario_real(caminho):
    filtrado = filtrar_sumario(caminho.read_text(encoding="utf-8"))
    assert not re.search(r"Resumo:\s*(Não há|Não existe|Não menciona|Nenhum)", filtrado)


@pytest.mark.parametrize("caminho", SUMARIOS_REAIS, ids=lambda p: p.name.split("_")[0])
def test_conteudo_de_contexto_e_preservado(caminho):
    """O filtro não pode comer as seções de texto livre, que são a âncora
    factual do sumário."""
    filtrado = filtrar_sumario(caminho.read_text(encoding="utf-8"))
    assert filtrado.startswith("Contexto")
    assert "Objetivo da reunião" in filtrado


@pytest.mark.parametrize(
    "job,trecho",
    [
        # As quatro premissas sem lastro que o comparativo rastreou até o
        # sumário e que o filtro alcança (docs/COMPARATIVO_IMPLICITAS_V4_V6.md).
        ("00c2ff18", "depende da validação das novas datas"),
        ("00c2ff18", "data exata da reunião anterior"),
        ("50098d37", "interface gráfica depende da geração"),
        ("50098d37", "Não há prazo explícito mencionado"),
    ],
)
def test_premissa_sem_lastro_nao_chega_ao_gerador_de_perguntas(job, trecho):
    bruto = _ler(job)
    assert trecho in bruto, "fixture perdeu a premissa que deveria exercitar"
    assert trecho not in filtrar_sumario(bruto)


def test_o_fato_inventado_em_secao_explicita_sobrevive_e_e_intencional():
    """O "30 de outubro" está em Pendências, é estruturalmente válido e só o
    confronto com a transcrição o denuncia. O filtro NÃO o alcança — fixar
    isso em teste evita que alguém leia o filtro como solução completa. É a
    classe que ficaria para um meeting_summary_v2."""
    filtrado = filtrar_sumario(_ler("2e335c5c"))
    assert "30 de outubro" in filtrado


def test_nenhum_elemento_com_lastro_e_perdido_das_secoes_explicitas():
    """Contra-prova: das seções explícitas só podem sair os placeholders de
    ausência — três, todos em 50098d37."""
    removidos_legitimos = {"PR1", "O1", "DV1"}
    bruto = _ler("50098d37")
    antes = set(RE_ELEMENTO.findall(bruto))
    depois = set(RE_ELEMENTO.findall(filtrar_sumario(bruto)))
    # Prefixos das seções 5 e 6, descartadas por inteiro.
    inferencia = {"CI", "CE", "DI", "PP", "RI", "M", "PM", "RE", "OI", "SR", "CF", "CT", "PV"}
    perdidos = {
        e for e in antes - depois if re.match(r"^([A-Z]+)", e).group(1) not in inferencia
    }
    assert perdidos == removidos_legitimos


# --------------------------------------------------------------------------
# Bordas de formato
# --------------------------------------------------------------------------


def test_sumario_vazio_passa_vazio():
    """Caminho de ENABLE_IMPLICIT_QUESTIONS=false, em que pipeline_facade
    entrega string vazia sem chamar o Ollama."""
    assert filtrar_sumario("") == ""
    assert filtrar_sumario("   \n  ") == "   \n  "


def test_sumario_sem_secao_reconhecida_e_erro_explicito():
    """Não repassa o texto cru: repassar devolveria em silêncio a
    contaminação que o filtro existe para conter."""
    with pytest.raises(ValueError, match="seção de topo"):
        filtrar_sumario("O modelo resolveu responder em prosa livre hoje.")


def test_cabecalho_numerado_e_reconhecido():
    """O prompt numera as seções no schema ("5. Lacunas"); o modelo às vezes
    reproduz a numeração."""
    sumario = "1. Contexto\n\nObjetivo da reunião:\nX.\n\n5. Lacunas\n\nPontos vagos\n\n- id: PV1\n  Resumo: Algo vago.\n"
    filtrado = filtrar_sumario(sumario)
    assert "Objetivo da reunião" in filtrado
    assert "PV1" not in filtrado


def test_secao_ausente_nao_quebra_o_filtro():
    """50098d37 omitiu "Estrutura da discussão" inteira apesar da regra de
    validação 1 do prompt."""
    filtrado = filtrar_sumario(_ler("50098d37"))
    assert "Estrutura da discussão" not in filtrado
    assert "Conteúdo explícito" in filtrado


def test_categoria_que_fica_sem_elementos_sai_junto_com_o_cabecalho():
    sumario = (
        "Contexto\n\nObjetivo da reunião:\nX.\n\n"
        "Conteúdo explícito\n\n"
        "Prazos\n\n- id: PR1\n  Resumo: Não há prazo mencionado.\n\n"
        "Tarefas\n\n- id: T1\n  Resumo: Revisar o texto.\n"
    )
    filtrado = filtrar_sumario(sumario)
    assert "Prazos" not in filtrado
    assert "Tarefas" in filtrado and "Revisar o texto" in filtrado


def test_sentinela_de_categoria_vazia_nao_vira_ruido():
    """6150ce54 trouxe 33 "Nenhum elemento identificado." — correto pelo
    prompt, mas informação zero para o gerador de perguntas."""
    filtrado = filtrar_sumario(_ler("6150ce54"))
    assert "Nenhum elemento identificado" not in filtrado


def test_elemento_legitimo_com_nao_no_meio_do_resumo_e_preservado():
    """O corte é por ABERTURA do resumo. Um elemento real que apenas contenha
    "não" no meio não pode ser confundido com placeholder de ausência."""
    sumario = (
        "Contexto\n\nObjetivo da reunião:\nX.\n\n"
        "Conteúdo explícito\n\n"
        "Problemas\n\n- id: P1\n  Resumo: A equipe não conseguiu reproduzir o erro.\n"
    )
    assert "não conseguiu reproduzir" in filtrar_sumario(sumario)
