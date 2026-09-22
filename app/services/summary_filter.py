"""Filtro estrutural do sumário, aplicado na fronteira entre
`summarize_meeting` e `extract_implicit_questions`.

POR QUE ISSO EXISTE
-------------------
O comparativo v4 × v6 (docs/COMPARATIVO_IMPLICITAS_V4_V6.md) rastreou toda
premissa sem lastro das perguntas implícitas até o sumário: o prompt de
implícitas — v4 ou v6 — não confabula sozinho, ele lê com fidelidade um insumo
já contaminado. As contaminações se separam em três classes, e este módulo
ataca duas delas SEM tocar em `prompts/meeting_summary_v1.txt` (regra 9 do
AGENTS.md: prompts são preservados semanticamente):

1. Inferência sancionada lida como fato. As seções "Conhecimento implícito" e
   "Lacunas" funcionam exatamente como o prompt as especifica — o defeito é de
   composição: elas chegam ao gerador de perguntas misturadas ao conteúdo
   explícito, sem marcação que as distinga. O campo `Confiança` deveria ser
   essa marcação (0.2 = criado exclusivamente por inferência), e no corpus
   medido ele está invertido: 20 de 20 elementos dessas seções vieram com
   0.5–1.0, enquanto 5 dos 6 usos de 0.2 foram em placeholders de ausência.
   Não dá para filtrar por confiança; dá para filtrar por seção.
2. Placeholders de ausência ("Resumo: Não há divergências explícitas
   mencionadas."). O prompt já os proíbe duas vezes (restrição "Não crie
   elementos apenas para declarar a ausência de informação" e regra de
   validação 7), e o modelo os produz assim mesmo — 10 no corpus medido.

A terceira classe (fato inventado dentro de seção explícita — o "30 de
outubro") NÃO é alcançável por filtro: o elemento é estruturalmente válido e
só o confronto com a transcrição revela a invenção. Ela fica para um eventual
`meeting_summary_v2.txt`.

O QUE ENTRA E O QUE SAI
-----------------------
Mantidas na íntegra: "Contexto" e "Estrutura da discussão" (texto livre, sem
blocos de elemento).
Mantidas com filtragem de elementos: "Conteúdo explícito" e "Conteúdo
argumentativo".
Descartadas inteiras: "Conhecimento implícito" e "Lacunas".

O sumário é artefato interno de consumidor único — não entra no MeetingResult
nem é persistido —, então filtrá-lo não toca em nenhum contrato do Flutter.
"""
import logging
import re
import unicodedata
from typing import List, Optional

logger = logging.getLogger(__name__)

# Seções de topo do schema de meeting_summary_v1.txt, na ordem em que o prompt
# as define. O modelo às vezes omite uma seção inteira (visto em 50098d37, que
# não trouxe "Estrutura da discussão" apesar da regra de validação 1), então o
# parser tolera ausências — só não tolera não reconhecer nenhuma.
SECOES_TEXTO_LIVRE = ("Contexto", "Estrutura da discussão")
SECOES_COM_ELEMENTOS = ("Conteúdo explícito", "Conteúdo argumentativo")
SECOES_DESCARTADAS = ("Conhecimento implícito", "Lacunas")
SECOES_DE_TOPO = SECOES_TEXTO_LIVRE + SECOES_COM_ELEMENTOS + SECOES_DESCARTADAS

# Sentinela de categoria vazia que o próprio prompt define (regras 6 e 19).
# Não é confabulação — é a saída correta —, mas não carrega informação para o
# gerador de perguntas e chega a dominar o sumário de uma reunião trivial (33
# ocorrências em 6150ce54), então sai junto com a categoria que a contém.
SENTINELA_CATEGORIA_VAZIA = "nenhum elemento identificado"

# Início de um bloco de elemento. Os 61 elementos do corpus medido usam
# exatamente "- id: ", sem variação.
RE_INICIO_ELEMENTO = re.compile(r"^\s*-\s*id:\s*\S+", re.IGNORECASE)
RE_CAMPO_RESUMO = re.compile(r"^\s*Resumo:\s*(.*)$", re.IGNORECASE)

# Numeração opcional que o modelo pode prefixar ao cabeçalho ("5. Lacunas").
RE_NUMERACAO = re.compile(r"^\s*\d+\s*[.)-]?\s*")

# Aberturas que caracterizam um elemento criado só para declarar ausência. As
# três primeiras são as que a regra de validação 7 do prompt cita
# literalmente; as demais saíram do corpus medido.
ABERTURAS_DE_AUSENCIA = (
    "nao ha",
    "nao existe",
    "nao mencionado",
    "nao menciona",
    "nao foi mencionado",
    "nao foi menciona",
    "nao consta",
    "nao houve",
    "nao apresenta",
    "nao foram identificados",
    "nao foi identificado",
    "nenhum elemento",
    "nenhuma informacao",
)


def _normalizar(texto: str) -> str:
    """Sem acento, minúsculas, pontuação virando espaço, espaços colapsados —
    para comparar cabeçalho e abertura de Resumo sem depender de como o modelo
    acentuou ou pontuou."""
    decomposto = unicodedata.normalize("NFKD", texto)
    sem_acento = "".join(c for c in decomposto if not unicodedata.combining(c))
    sem_pontuacao = re.sub(r"[^0-9a-z]+", " ", sem_acento.lower())
    return sem_pontuacao.strip()


_SECOES_NORMALIZADAS = {_normalizar(s): s for s in SECOES_DE_TOPO}


def _secao_de_topo(linha: str) -> Optional[str]:
    """Devolve o nome canônico da seção se a linha for um cabeçalho de topo.

    Casar pelo nome (e não por indentação ou espaço à direita) é deliberado: a
    convenção de espaço em branco varia entre execuções do mesmo prompt — em
    50098d37 os cabeçalhos de categoria terminam com dois espaços, em 00c2ff18
    não terminam —, então whitespace não distingue topo de categoria.
    """
    if linha.startswith((" ", "\t", "-")):
        return None
    return _SECOES_NORMALIZADAS.get(_normalizar(RE_NUMERACAO.sub("", linha)))


def _e_ausencia(resumo: str) -> bool:
    normalizado = _normalizar(resumo)
    return any(normalizado.startswith(a) for a in ABERTURAS_DE_AUSENCIA)


def _e_sentinela(linha: str) -> bool:
    return _normalizar(linha).startswith(SENTINELA_CATEGORIA_VAZIA)


class _Elemento:
    """Bloco "- id: X" com suas linhas de campo indentadas."""

    def __init__(self, linhas: List[str]) -> None:
        self.linhas = linhas

    @property
    def resumo(self) -> str:
        for linha in self.linhas:
            achado = RE_CAMPO_RESUMO.match(linha)
            if achado:
                return achado.group(1)
        return ""

    @property
    def identificador(self) -> str:
        return self.linhas[0].strip() if self.linhas else "?"


def _coletar_elemento(linhas: List[str], inicio: int) -> int:
    """Índice da primeira linha APÓS o bloco de elemento que começa em
    `inicio`. O bloco termina na primeira linha em branco ou na primeira linha
    não indentada (próxima categoria, próxima seção ou próximo elemento)."""
    fim = inicio + 1
    while fim < len(linhas):
        linha = linhas[fim]
        if not linha.strip():
            break
        if not linha.startswith((" ", "\t")):
            break
        fim += 1
    return fim


def _filtrar_secao_texto_livre(linhas: List[str]) -> List[str]:
    """Filtra "Contexto"/"Estrutura da discussão".

    Essas seções não usam blocos "- id:": são campos do schema ("Objetivo da
    reunião:", "Dependências:") seguidos de texto livre ou de bullets. Um
    campo cujo conteúdo seja apenas a sentinela de categoria vazia sai inteiro
    — numa conversa trivial toda a "Estrutura da discussão" é só sentinela, e
    entregá-la ao gerador de perguntas é ruído puro.
    """
    blocos: List[List[str]] = []
    cabecalho_visto = False

    for linha in linhas:
        if not linha.strip():
            continue
        if linha.rstrip().endswith(":") and not linha.startswith((" ", "\t", "-")):
            blocos.append([linha])
            cabecalho_visto = True
        elif cabecalho_visto:
            blocos[-1].append(linha)
        else:
            # Texto solto antes do primeiro campo: preserva como bloco próprio.
            blocos.append([linha])

    saida: List[str] = []
    for bloco in blocos:
        corpo = bloco[1:] if bloco[0].rstrip().endswith(":") else bloco
        if corpo and all(_e_sentinela(l) for l in corpo):
            continue
        if bloco[0].rstrip().endswith(":") and not corpo:
            continue
        saida.extend(bloco)
        saida.append("")

    return saida


def _filtrar_secao_com_elementos(linhas: List[str]) -> List[str]:
    """Filtra o corpo de "Conteúdo explícito"/"Conteúdo argumentativo".

    A forma dessas seções é estrita: cabeçalho de categoria, linha em branco,
    blocos de elemento (ou a sentinela de categoria vazia). Uma categoria que
    fique sem nenhum elemento depois do filtro sai junto com o cabeçalho — não
    faz sentido entregar ao gerador de perguntas um título sem conteúdo.
    """
    saida: List[str] = []
    categoria_atual: Optional[str] = None
    elementos_da_categoria: List[_Elemento] = []

    def fechar_categoria() -> None:
        nonlocal categoria_atual, elementos_da_categoria
        if categoria_atual is not None and elementos_da_categoria:
            saida.append(categoria_atual)
            saida.append("")
            for elemento in elementos_da_categoria:
                saida.extend(elemento.linhas)
                saida.append("")
        categoria_atual = None
        elementos_da_categoria = []

    i = 0
    while i < len(linhas):
        linha = linhas[i]

        if not linha.strip():
            i += 1
            continue

        if RE_INICIO_ELEMENTO.match(linha):
            fim = _coletar_elemento(linhas, i)
            elemento = _Elemento(linhas[i:fim])
            if _e_ausencia(elemento.resumo):
                logger.info(
                    "summary_filter: elemento de ausência descartado (%s): %s",
                    elemento.identificador,
                    elemento.resumo.strip()[:80],
                )
            else:
                elementos_da_categoria.append(elemento)
            i = fim
            continue

        if _e_sentinela(linha):
            # Categoria declarada vazia pelo próprio prompt: nada a manter.
            i += 1
            continue

        # Sobrou: cabeçalho de categoria.
        fechar_categoria()
        categoria_atual = linha
        i += 1

    fechar_categoria()
    return saida


def filtrar_sumario(sumario: str) -> str:
    """Entrega só o conteúdo com lastro na transcrição.

    Sumário vazio passa vazio (é o caminho de ENABLE_IMPLICIT_QUESTIONS=false,
    onde `pipeline_facade` nem chama o Ollama).

    Sumário não vazio em que NENHUMA seção de topo é reconhecida levanta
    ValueError em vez de repassar o texto cru. É deliberado: o filtro existe
    para garantir que só material com lastro chegue ao gerador de perguntas, e
    repassar um sumário que não se sabe interpretar devolveria em silêncio
    exatamente a contaminação que esta etapa foi criada para conter — o job
    produziria perguntas de aparência normal carregando o defeito. Falhar alto
    é a mesma decisão já tomada no parser do v6 para formato inesperado.
    """
    if not sumario.strip():
        return sumario

    linhas = sumario.split("\n")
    secoes: List[tuple] = []  # (nome_canonico, linha_original, corpo)
    for indice, linha in enumerate(linhas):
        nome = _secao_de_topo(linha)
        if nome is not None:
            secoes.append((nome, linha, indice))

    if not secoes:
        raise ValueError(
            "Sumário sem nenhuma seção de topo reconhecida "
            f"(esperadas: {', '.join(SECOES_DE_TOPO)}). "
            "O formato de meeting_summary mudou ou o modelo saiu do schema."
        )

    saida: List[str] = []
    for posicao, (nome, linha_cabecalho, indice) in enumerate(secoes):
        fim = secoes[posicao + 1][2] if posicao + 1 < len(secoes) else len(linhas)
        corpo = linhas[indice + 1 : fim]

        if nome in SECOES_DESCARTADAS:
            logger.info("summary_filter: seção %r descartada (%d linhas).", nome, len(corpo))
            continue

        if nome in SECOES_TEXTO_LIVRE:
            corpo_filtrado = _filtrar_secao_texto_livre(corpo)
        else:
            corpo_filtrado = _filtrar_secao_com_elementos(corpo)

        if not corpo_filtrado:
            logger.info("summary_filter: seção %r ficou vazia após o filtro.", nome)
            continue

        saida.append(linha_cabecalho.rstrip())
        saida.append("")
        saida.extend(corpo_filtrado)
        saida.append("")

    return "\n".join(saida).strip() + "\n"
