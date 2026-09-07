"""Os códigos de fechamento do WebSocket, contra um servidor HTTP de verdade.

Existe por um bug que passou por toda a suíte: `close(4401)` era chamado
ANTES de `accept()`, e nessa ordem o servidor ASGI recusa o próprio handshake
com HTTP 403 — o cliente recebe um erro de conexão, sem close code nenhum. O
4401 que o código parecia emitir nunca chegava ao app.

O TestClient do Starlette não pega isso: ele entrega a mensagem de close
direto pelo ASGI, sem handshake HTTP, então `close()` antes ou depois do
`accept()` produzem o mesmo resultado observável. Os testes de
test_jobs_websocket.py afirmavam 4401 e passavam, com a API real devolvendo
403 — descoberto só ao exercitar o servidor implantado, em 07/09/2026.

Daí um uvicorn de verdade numa porta efêmera e um cliente WebSocket real.
Vale o custo (~1s) para esta classe de bug, que é invisível de outro jeito.
"""
import socket
import threading
import time

import pytest
import uvicorn
from websockets.sync.client import connect as ws_connect

from app.main import app


def _porta_livre() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture
def servidor_real():
    """uvicorn de verdade, numa thread, numa porta efêmera."""
    porta = _porta_livre()
    config = uvicorn.Config(app, host="127.0.0.1", port=porta, log_level="warning")
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()

    limite = time.monotonic() + 15
    while not server.started and time.monotonic() < limite:
        time.sleep(0.05)
    assert server.started, "uvicorn não subiu a tempo"

    yield f"ws://127.0.0.1:{porta}"

    server.should_exit = True
    thread.join(timeout=10)


def _codigo_de_fechamento(url: str) -> int:
    """O close code que um cliente WebSocket REAL observa."""
    with ws_connect(url) as ws:
        with pytest.raises(Exception) as exc:
            ws.recv(timeout=10)
    recebido = getattr(exc.value, "rcvd", None)
    assert recebido is not None, f"esperava um frame de close, veio {exc.value!r}"
    return recebido.code


@pytest.mark.parametrize(
    "token, descricao",
    [("", "sem token"), ("nao.e.um.jwt", "token malformado")],
)
def test_cliente_real_recebe_4401_e_nao_um_403_de_handshake(servidor_real, token, descricao):
    """A regressão. Sem o accept() antes do close, isto levanta InvalidStatus
    (HTTP 403) na conexão e nem chega a haver close code."""
    url = f"{servidor_real}/ws/qualquer-job" + (f"?token={token}" if token else "")
    assert _codigo_de_fechamento(url) == 4401, descricao


def test_cliente_real_recebe_4404_em_job_que_nao_e_dele(servidor_real, client, wav_bytes):
    """O outro caminho, que já aceitava antes de fechar — aqui para os dois
    ficarem cobertos pelo mesmo tipo de teste, e para provar que continuam
    distinguíveis entre si por um cliente de verdade."""
    token = client.headers["Authorization"].removeprefix("Bearer ")
    codigo = _codigo_de_fechamento(f"{servidor_real}/ws/job-que-nao-existe?token={token}")
    assert codigo == 4404
