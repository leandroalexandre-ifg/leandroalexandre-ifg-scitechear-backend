"""CORS: origem configurável e a relação entre origem e credenciais.

O comentário original do main.py pedia "restringir origens antes de qualquer
deploy fora do ambiente de testes" — o deploy no servidor aconteceu antes
disso ser feito. Estes testes travam o comportamento das duas pontas.
"""
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import configurar_cors


def _app_com_origens(valor: str) -> TestClient:
    app = FastAPI()

    @app.get("/eco")
    def eco():
        return {"ok": True}

    configurar_cors(app, Settings(CORS_ALLOW_ORIGINS=valor))
    return TestClient(app)


def test_origem_curinga_nao_libera_credenciais():
    """`Access-Control-Allow-Origin: *` com `Allow-Credentials: true` é a
    combinação que o CORS proíbe — e que o Starlette contorna ecoando a
    origem de quem pediu, liberando credenciais para qualquer site. Nada no
    projeto depende disso: a autenticação é Bearer, não cookie."""
    client = _app_com_origens("*")
    resposta = client.get("/eco", headers={"Origin": "https://site-qualquer.exemplo"})

    assert resposta.headers["access-control-allow-origin"] == "*"
    assert "access-control-allow-credentials" not in resposta.headers


def test_lista_explicita_aceita_a_origem_conhecida_e_permite_credenciais():
    client = _app_com_origens("https://app.exemplo, https://outro.exemplo")
    resposta = client.get("/eco", headers={"Origin": "https://app.exemplo"})

    assert resposta.headers["access-control-allow-origin"] == "https://app.exemplo"
    assert resposta.headers["access-control-allow-credentials"] == "true"


def test_lista_explicita_nao_ecoa_origem_desconhecida():
    client = _app_com_origens("https://app.exemplo")
    resposta = client.get("/eco", headers={"Origin": "https://site-malicioso.exemplo"})

    assert resposta.status_code == 200  # a requisição em si não é bloqueada pelo servidor
    assert "access-control-allow-origin" not in resposta.headers


def test_default_preserva_o_comportamento_de_desenvolvimento():
    """Sem CORS_ALLOW_ORIGINS no ambiente, nada muda em relação ao que o
    projeto fazia antes desta configuração existir.

    `_env_file=None` não é detalhe de estilo. Sem ele, `Settings()` lê o `.env`
    do servidor, e este teste passa a medir o que a PRODUÇÃO configurou em vez
    do default do campo — dois valores que só coincidiam enquanto a variável
    estivesse ausente do arquivo. Em 2026-09-21 ela foi explicitada (vazia,
    para a exposição de rede) e a versão antiga deste teste quebraria ali, sem
    que comportamento nenhum tivesse mudado.
    """
    assert Settings(_env_file=None).cors_allow_origins_list == ["*"]


def test_vazio_nao_libera_origem_nenhuma():
    """O valor que a produção passou a usar. Vazio é diferente de ausente:
    ausente cai no default `*`, vazio nega toda origem web — que é o
    pretendido, já que o cliente é Android nativo e não manda `Origin`."""
    client = _app_com_origens("")
    resposta = client.get("/eco", headers={"Origin": "https://site-qualquer.exemplo"})

    assert resposta.status_code == 200
    assert "access-control-allow-origin" not in resposta.headers
