"""Os diagramas SVG conferidos contra o código.

Existe por um problema que o frontend nomeou bem em 07/09/2026: nada obriga
uma figura a acompanhar o código. Os documentos em prosa foram corrigidos
várias vezes nas últimas rodadas; os diagramas, nenhuma — e uma figura errada
convence mais que um parágrafo errado, porque parece um resumo autorizado.

Três erros reais motivaram cada checagem daqui:

- `01` e `04` mostravam o processamento como "background thread" da API muito
  depois de ele ter virado um worker em processo separado. Quem fosse operar
  o sistema pelo diagrama concluiria que subir a API basta — e o job ficaria
  em `queued` para sempre, sem sinal nenhum.
- `03` afirmava que "o cliente exibe error.message", o que deixou de ser
  verdade quando o app passou a traduzir o `error.code`. O `message` é
  `str(exc)` da exceção Python e pode conter caminho de arquivo do servidor.
- um `<user_id>` escrito com `<` e `>` crus quebrou o XML de `01` e não foi
  notado a olho nu.

Nenhuma destas asserções verifica desenho — só afirmações que o código pode
desmentir.
"""
import re
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

from app.main import app
from app.models.job import JobStatusValue

NS = "{http://www.w3.org/2000/svg}"
DIAGRAMAS = sorted((Path(__file__).resolve().parent.parent / "docs" / "diagrams").glob("*.svg"))


def _texto(svg: Path) -> str:
    raiz = ET.parse(svg).getroot()
    return " ".join(t.text.strip() for t in raiz.iter(NS + "text") if t.text and t.text.strip())


@pytest.fixture(scope="module")
def textos():
    return {svg.name: _texto(svg) for svg in DIAGRAMAS}


def test_existe_diagrama_para_conferir():
    assert DIAGRAMAS, "nenhum SVG encontrado em docs/diagrams/"


@pytest.mark.parametrize("svg", DIAGRAMAS, ids=lambda p: p.name)
def test_svg_e_xml_valido(svg):
    """`<user_id>` cru quebrou um diagrama sem ninguém perceber: o arquivo
    continua no repositório e simplesmente não renderiza."""
    ET.parse(svg)


# Frases que já estiveram num diagrama e deixaram de ser verdade. Cada uma
# custou uma rodada de revisão para alguém notar.
FRASES_MORTAS = [
    ("background thread", "o processamento é um worker em processo separado (app/worker.py)"),
    ("job_executor", "não existe: virou app/worker.py + app/services/job_runner.py"),
    ("exibe error.message", "o app traduz o error.code; o message nunca chega à tela"),
    ("estado do job em memória", "os jobs vivem em SQLite (WAL), não em memória"),
]


@pytest.mark.parametrize("frase, motivo", FRASES_MORTAS, ids=lambda v: v[:28] if isinstance(v, str) else "")
def test_nenhum_diagrama_repete_afirmacao_que_deixou_de_ser_verdade(frase, motivo, textos):
    culpados = [nome for nome, txt in textos.items() if frase.lower() in txt.lower()]
    assert not culpados, f"{culpados} ainda dizem {frase!r} — {motivo}"


def test_estados_do_job_no_diagrama_batem_com_o_enum():
    """`03` desenha a máquina de estados: se o enum ganhar ou perder um
    estado, o diagrama passa a mentir sobre o contrato.

    Confere os RÓTULOS das caixas, não o texto corrido: a primeira versão
    procurava a substring no diagrama inteiro e passava mesmo com a caixa
    renomeada, porque o rodapé cita `identifying` em prosa.
    """
    svg = next(d for d in DIAGRAMAS if d.name == "03-job-state-machine.svg")
    raiz = ET.parse(svg).getroot()
    rotulos = {t.text.strip() for t in raiz.iter(NS + "text") if t.text and t.text.strip()}
    for estado in JobStatusValue:
        assert estado.value in rotulos, (
            f"nenhuma caixa do diagrama é rotulada {estado.value!r} "
            "(citar o estado no texto corrido não conta)"
        )


def _rotas_reais() -> set[str]:
    return {re.sub(r"\{[^}]+\}", "{}", r.path) for r in app.routes if hasattr(r, "path")}


# Só citações precedidas de método HTTP. Uma primeira versão varria qualquer
# token com "/" e acusou 19 falsos positivos (app/api, Celery/Redis,
# WhisperX turbo/pt, threshold/margem/outlier...): barra é usada para muita
# coisa em texto livre, e um teste que grita sem motivo é desligado na
# primeira semana. Com o método na frente, a citação é inequívoca.
CITACAO_DE_ROTA = re.compile(r"\b(GET|POST|PATCH|DELETE|WS)\s+(/[\w/{}<>.-]*)")


def test_toda_rota_citada_com_metodo_existe_de_fato(textos):
    """Impede o inverso do erro do worker: um diagrama anunciando rota que a
    API não serve, ou que foi renomeada e ninguém redesenhou.

    Cobertura parcial e assumida: uma rota citada sem método (numa lista como
    "/upload · /status · /resultado") não é conferida aqui. Não há como
    distinguir isso de um caminho de disco sem uma lista fixa de rotas — que
    é exatamente o que envelheceria junto com o diagrama.
    """
    reais = _rotas_reais()
    fantasmas = []
    for nome, txt in textos.items():
        for metodo, bruto in CITACAO_DE_ROTA.findall(txt):
            caminho = re.sub(r"\{[^}]+\}|<[^>]+>", "{}", bruto).rstrip("/")
            if caminho in reais or caminho + "/{}" in reais:
                continue
            fantasmas.append((nome, f"{metodo} {bruto}"))
    assert not fantasmas, f"rotas citadas em diagrama que a API não serve: {fantasmas}"


def test_todo_diagrama_esta_referenciado_em_alguma_documentacao():
    """Um SVG que ninguém referencia envelhece sem ninguém ver."""
    raiz = Path(__file__).resolve().parent.parent
    markdown = " ".join(p.read_text(encoding="utf-8") for p in
                        [*(raiz / "docs").glob("*.md"), raiz / "README.md"])
    orfaos = [svg.name for svg in DIAGRAMAS if svg.name not in markdown]
    assert not orfaos, f"diagramas que nenhum documento referencia: {orfaos}"
