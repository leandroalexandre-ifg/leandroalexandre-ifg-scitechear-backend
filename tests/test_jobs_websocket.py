"""Contrato do WS /ws/{job_id} — push de progresso do job.

Não sobe worker nenhum: as transições de estado são simuladas escrevendo no
mesmo repositório que o worker escreveria. O que está sob teste é o handler
da API (autenticação, isolamento por usuário, o que é empurrado e quando a
conexão fecha), não o pipeline.
"""
import json

import pytest
from starlette.websockets import WebSocketDisconnect

from app.config import get_settings
from app.models.job import JobError, JobStatusValue
from app.repositories.job_repository import get_job_repository


@pytest.fixture(autouse=True)
def ws_rapido(monkeypatch):
    """Sem isso cada transição custaria 1s de relógio real na suíte."""
    monkeypatch.setenv("WS_POLL_INTERVAL_SECONDS", "0.01")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def _upload(client, wav_bytes):
    return client.post(
        "/upload",
        data={"title": "Reunião de teste", "participants": json.dumps([{"id": "p1", "name": "Leandro"}])},
        files={"file": ("reuniao.wav", wav_bytes, "audio/wav")},
    )


def _token(client) -> str:
    return client.headers["Authorization"].removeprefix("Bearer ")


def test_ws_sem_token_e_recusado(client, wav_bytes):
    job_id = _upload(client, wav_bytes).json()["job_id"]
    with pytest.raises(WebSocketDisconnect) as exc:
        with client.websocket_connect(f"/ws/{job_id}") as ws:
            ws.receive_json()
    assert exc.value.code == 4401


def test_ws_token_invalido_e_recusado(client, wav_bytes):
    job_id = _upload(client, wav_bytes).json()["job_id"]
    with pytest.raises(WebSocketDisconnect) as exc:
        with client.websocket_connect(f"/ws/{job_id}?token=nao-e-um-token") as ws:
            ws.receive_json()
    assert exc.value.code == 4401


def test_ws_job_inexistente_fecha_4404(client):
    with pytest.raises(WebSocketDisconnect) as exc:
        with client.websocket_connect(f"/ws/nao-existe?token={_token(client)}") as ws:
            ws.receive_json()
    assert exc.value.code == 4404


def test_ws_nao_entrega_job_de_outro_usuario(client, unauthenticated_client, wav_bytes):
    """Mesmo isolamento por user_id das rotas HTTP: o job existe, mas não é
    de quem está pedindo — e a resposta é indistinguível de 'não existe'."""
    job_id = _upload(client, wav_bytes).json()["job_id"]

    outro = unauthenticated_client
    outro.post("/auth/register", json={"email": "outro@scitechear.example.com",
                                       "password": "outra-senha-123", "name": "Outro"})
    login = outro.post("/auth/login", json={"email": "outro@scitechear.example.com",
                                            "password": "outra-senha-123"})
    token_do_outro = login.json()["access_token"]

    with pytest.raises(WebSocketDisconnect) as exc:
        with outro.websocket_connect(f"/ws/{job_id}?token={token_do_outro}") as ws:
            ws.receive_json()
    assert exc.value.code == 4404


def test_ws_envia_o_estado_atual_ao_conectar(client, wav_bytes):
    job_id = _upload(client, wav_bytes).json()["job_id"]
    with client.websocket_connect(f"/ws/{job_id}?token={_token(client)}") as ws:
        payload = ws.receive_json()

    assert payload["job_id"] == job_id
    assert payload["status"] == "queued"


def test_ws_payload_e_igual_ao_de_get_status(client, wav_bytes):
    """O app precisa de um parser só para polling e WebSocket — se os dois
    corpos divergirem, é aqui que o teste quebra."""
    job_id = _upload(client, wav_bytes).json()["job_id"]
    via_http = client.get(f"/status/{job_id}").json()
    with client.websocket_connect(f"/ws/{job_id}?token={_token(client)}") as ws:
        via_ws = ws.receive_json()

    assert via_ws == via_http
    assert set(via_ws) == {"job_id", "status", "progress", "error", "updated_at"}


def test_ws_empurra_cada_transicao_ate_done(client, wav_bytes):
    job_id = _upload(client, wav_bytes).json()["job_id"]
    repositorio = get_job_repository()

    with client.websocket_connect(f"/ws/{job_id}?token={_token(client)}") as ws:
        assert ws.receive_json()["status"] == "queued"

        for estado in [JobStatusValue.TRANSCRIBING, JobStatusValue.DIARIZING, JobStatusValue.DONE]:
            repositorio.update_status(job_id, estado)
            assert ws.receive_json()["status"] == estado.value

        # Chegou a um estado final: o servidor encerra sozinho, sem o app
        # precisar fechar nem continuar perguntando.
        with pytest.raises(WebSocketDisconnect):
            ws.receive_json()


def test_ws_nao_repete_mensagem_quando_nada_muda(client, wav_bytes):
    """Um job parado 40s em transcribing não pode virar 40 mensagens iguais."""
    job_id = _upload(client, wav_bytes).json()["job_id"]
    repositorio = get_job_repository()

    with client.websocket_connect(f"/ws/{job_id}?token={_token(client)}") as ws:
        assert ws.receive_json()["status"] == "queued"
        repositorio.update_status(job_id, JobStatusValue.TRANSCRIBING)
        assert ws.receive_json()["status"] == "transcribing"

        # Várias voltas do laço de polling acontecem aqui sem nenhuma
        # mudança de estado; a próxima mensagem só chega quando o estado
        # muda de novo.
        repositorio.update_status(job_id, JobStatusValue.DONE)
        assert ws.receive_json()["status"] == "done"


def test_ws_entrega_erro_real_e_fecha(client, wav_bytes):
    """Erro do backend chega ao app como erro — nunca vira resultado
    fictício nem some no silêncio de uma conexão pendurada (regra 5)."""
    job_id = _upload(client, wav_bytes).json()["job_id"]
    repositorio = get_job_repository()

    with client.websocket_connect(f"/ws/{job_id}?token={_token(client)}") as ws:
        assert ws.receive_json()["status"] == "queued"
        repositorio.update_status(
            job_id,
            JobStatusValue.ERROR,
            error=JobError(code="EXTRACTION_ERROR", message="Ollama indisponível."),
        )
        payload = ws.receive_json()

    assert payload["status"] == "error"
    assert payload["error"] == {"code": "EXTRACTION_ERROR", "message": "Ollama indisponível."}


def test_ws_de_job_ja_finalizado_envia_uma_vez_e_fecha(client, wav_bytes):
    """Conectar depois que o job acabou (app reaberto, tela retomada) não
    deixa a conexão pendurada esperando um evento que nunca virá."""
    job_id = _upload(client, wav_bytes).json()["job_id"]
    get_job_repository().update_status(job_id, JobStatusValue.DONE)

    with client.websocket_connect(f"/ws/{job_id}?token={_token(client)}") as ws:
        assert ws.receive_json()["status"] == "done"
        with pytest.raises(WebSocketDisconnect):
            ws.receive_json()


def test_ws_fecha_ao_estourar_o_teto_de_vida(client, wav_bytes, monkeypatch):
    """Job travado não segura a conexão para sempre: a API fecha e o app
    volta ao polling."""
    monkeypatch.setenv("WS_MAX_DURATION_SECONDS", "0")
    get_settings.cache_clear()

    job_id = _upload(client, wav_bytes).json()["job_id"]
    with client.websocket_connect(f"/ws/{job_id}?token={_token(client)}") as ws:
        assert ws.receive_json()["status"] == "queued"
        with pytest.raises(WebSocketDisconnect):
            ws.receive_json()
