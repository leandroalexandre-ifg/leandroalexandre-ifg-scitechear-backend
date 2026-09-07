"""O JWT do WebSocket não pode chegar ao log de acesso.

Regressão de um vazamento real: em 2026-09-06 o journal do servidor de deploy
tinha quatro linhas de acesso com o token completo na query string, uma delas
ainda dentro da validade. Ver app/main.py.
"""

import logging

import pytest
from fastapi.testclient import TestClient

from app.main import (
    app,
    _LOGGERS_QUE_REGISTRAM_A_URL,
    RedigirTokenDeQueryString,
    instalar_filtro_de_token,
)

JWT = (
    "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9"
    ".eyJzdWIiOiJkODY0NjA0NC1iZDZlLTQ4NjUtOGJjYi1mMDNiMTY5YTc3ODQifQ"
    ".LnioPk8zI1INgb5QXUETo1CSffM8dY3haqOF5-WcenY"
)
JOB = "2accb704-02c7-4c75-b177-f8637d188eab"


def _registro_de_acesso_do_uvicorn(caminho: str) -> logging.LogRecord:
    """Reproduz como o uvicorn emite a linha do WebSocket.

    O caminho vem como ARGUMENTO de formatação, não interpolado na mensagem —
    é por isso que filtrar só record.msg não resolveria nada.
    """
    return logging.LogRecord(
        name="uvicorn.access",
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg='%s - "WebSocket %s" [accepted]',
        args=("127.0.0.1:44652", caminho),
        exc_info=None,
    )


def test_token_da_query_string_nao_sobrevive_a_formatacao():
    registro = _registro_de_acesso_do_uvicorn(f"/ws/{JOB}?token={JWT}")

    RedigirTokenDeQueryString().filter(registro)
    linha = registro.getMessage()

    assert JWT not in linha
    assert "eyJ" not in linha
    assert "token=REDACTED" in linha


def test_o_resto_da_linha_continua_util():
    registro = _registro_de_acesso_do_uvicorn(f"/ws/{JOB}?token={JWT}")

    RedigirTokenDeQueryString().filter(registro)
    linha = registro.getMessage()

    # Redigir não pode custar o diagnóstico: quem lê o log ainda precisa saber
    # qual job e qual cliente.
    assert JOB in linha
    assert "127.0.0.1:44652" in linha
    assert "[accepted]" in linha


def test_outros_parametros_da_query_sao_preservados():
    registro = _registro_de_acesso_do_uvicorn(f"/ws/{JOB}?token={JWT}&debug=1")

    RedigirTokenDeQueryString().filter(registro)
    linha = registro.getMessage()

    assert JWT not in linha
    assert "debug=1" in linha


def test_token_interpolado_na_mensagem_tambem_e_redigido():
    registro = logging.LogRecord(
        name="qualquer",
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg=f"falha ao abrir /ws/{JOB}?token={JWT}",
        args=None,
        exc_info=None,
    )

    RedigirTokenDeQueryString().filter(registro)

    assert JWT not in registro.getMessage()
    assert "token=REDACTED" in registro.getMessage()


def test_linha_sem_token_passa_intacta():
    registro = _registro_de_acesso_do_uvicorn(f"/status/{JOB}")

    RedigirTokenDeQueryString().filter(registro)

    assert registro.getMessage().endswith(f'"WebSocket /status/{JOB}" [accepted]')


def test_uvicorn_error_e_mesmo_quem_emite_a_linha_do_websocket():
    """Ancora a suposição que já errou uma vez.

    A primeira versão desta correção prendeu o filtro em "uvicorn.access" — o
    logger óbvio, e o errado. Os testes passaram e o token continuou indo para
    o journal do servidor. Este teste lê o código do uvicorn instalado: se uma
    atualização mudar o logger, ele quebra aqui em vez de quebrar em silêncio
    na produção.
    """
    import inspect

    from uvicorn.protocols.websockets import websockets_impl

    fonte = inspect.getsource(websockets_impl)
    assert '"WebSocket %s" [accepted]' in fonte, "o uvicorn mudou o formato da linha"
    assert 'getLogger("uvicorn.error")' in fonte, "o uvicorn mudou o logger da linha"
    assert "uvicorn.error" in _LOGGERS_QUE_REGISTRAM_A_URL


@pytest.mark.parametrize("nome_do_logger", _LOGGERS_QUE_REGISTRAM_A_URL)
def test_o_filtro_fica_preso_em_cada_logger_que_pode_emitir(nome_do_logger, caplog):
    """Sem isto o filtro existe e não protege nada."""
    logger_alvo = logging.getLogger(nome_do_logger)
    filtros_antes = list(logger_alvo.filters)
    try:
        instalar_filtro_de_token()

        assert any(
            isinstance(f, RedigirTokenDeQueryString) for f in logger_alvo.filters
        )

        with caplog.at_level(logging.INFO, logger=nome_do_logger):
            logger_alvo.info(
                '%s - "WebSocket %s" [accepted]',
                "10.4.1.99:51000",
                f"/ws/{JOB}?token={JWT}",
            )

        assert JWT not in caplog.text
        assert "token=REDACTED" in caplog.text
    finally:
        logger_alvo.filters = filtros_antes


def test_401_loga_o_motivo_sem_vazar_o_token(caplog):
    """Pedido do frontend para o teste conjunto (07/09/2026): distinguir, do
    lado do servidor, "o app não mandou token" de "mandou um que não serve".
    A restrição que anda junto: o motivo vai para o log, a credencial não."""
    sem_header = TestClient(app)

    with caplog.at_level(logging.INFO, logger="app.api.dependencies"):
        assert sem_header.get("/meetings").status_code == 401
    assert "401 em GET /meetings" in caplog.text
    assert "Authorization ausente" in caplog.text

    caplog.clear()
    token_falso = "nao.e.um.jwt.valido"
    sem_header.headers.update({"Authorization": f"Bearer {token_falso}"})
    with caplog.at_level(logging.INFO, logger="app.api.dependencies"):
        assert sem_header.get("/meetings").status_code == 401
    assert "inválido ou expirado" in caplog.text
    assert token_falso not in caplog.text
