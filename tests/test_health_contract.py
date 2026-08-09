import requests

import app.api.health as health_module
from app.config import get_settings


def test_health_nao_carrega_modelos(client):
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_ready_true_quando_hf_token_e_ollama_disponiveis(client, monkeypatch):
    monkeypatch.setenv("HF_TOKEN", "um-token-qualquer")
    get_settings.cache_clear()
    monkeypatch.setattr(health_module, "_ollama_disponivel", lambda base_url, timeout=2.0: True)

    try:
        response = client.get("/ready")
        assert response.status_code == 200
        body = response.json()
        assert body["ready"] is True
        assert body["checks"] == {"hf_token_configurado": True, "ollama_disponivel": True}
    finally:
        get_settings.cache_clear()


def test_ready_false_quando_hf_token_ausente(client, monkeypatch):
    monkeypatch.setenv("HF_TOKEN", "")
    get_settings.cache_clear()
    monkeypatch.setattr(health_module, "_ollama_disponivel", lambda base_url, timeout=2.0: True)

    try:
        response = client.get("/ready")
        body = response.json()
        assert body["ready"] is False
        assert body["checks"]["hf_token_configurado"] is False
    finally:
        get_settings.cache_clear()


def test_ready_false_quando_ollama_indisponivel(client, monkeypatch):
    monkeypatch.setenv("HF_TOKEN", "um-token-qualquer")
    get_settings.cache_clear()
    monkeypatch.setattr(health_module, "_ollama_disponivel", lambda base_url, timeout=2.0: False)

    try:
        response = client.get("/ready")
        body = response.json()
        assert body["ready"] is False
        assert body["checks"]["ollama_disponivel"] is False
    finally:
        get_settings.cache_clear()


def test_ready_nao_e_incondicional_falha_quando_tudo_indisponivel(client, monkeypatch):
    monkeypatch.setenv("HF_TOKEN", "")
    get_settings.cache_clear()
    monkeypatch.setattr(health_module, "_ollama_disponivel", lambda base_url, timeout=2.0: False)

    try:
        response = client.get("/ready")
        body = response.json()
        assert body["ready"] is False
        assert body["checks"] == {"hf_token_configurado": False, "ollama_disponivel": False}
    finally:
        get_settings.cache_clear()


def test_ollama_disponivel_retorna_false_em_erro_de_rede(monkeypatch):
    def _falha(*args, **kwargs):
        raise requests.ConnectionError("conexão recusada")

    monkeypatch.setattr(requests, "get", _falha)

    assert health_module._ollama_disponivel("http://localhost:1") is False


def test_ollama_disponivel_retorna_true_quando_responde_ok(monkeypatch):
    class _FakeResponse:
        ok = True

    monkeypatch.setattr(requests, "get", lambda url, timeout: _FakeResponse())

    assert health_module._ollama_disponivel("http://localhost:11434") is True
