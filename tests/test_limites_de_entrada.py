"""Limites que passam a valer quando a API deixa o loopback.

Enquanto o backend só respondia em 127.0.0.1, quem chegava à porta já estava
dentro da máquina. Com a rede do laboratório alcançando a API (docs/DEPLOY.md),
"qualquer um na rede" passa a incluir a instituição inteira — e estas duas
portas de entrada precisam de teto.
"""
import io
import json
import wave

import pytest

from app.config import get_settings
from app.repositories.storage_repository import ArquivoGrandeDemaisError, StorageRepository


def _wav(segundos: float = 0.1) -> bytes:
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as f:
        f.setnchannels(1)
        f.setsampwidth(2)
        f.setframerate(16000)
        f.writeframes(b"\x00\x00" * int(16000 * segundos))
    return buffer.getvalue()


def _upload(client, conteudo: bytes):
    return client.post(
        "/upload",
        data={"title": "Reunião", "participants": json.dumps([{"id": "p1", "name": "Leandro"}])},
        files={"file": ("reuniao.wav", conteudo, "audio/wav")},
    )


def test_upload_dentro_do_limite_e_aceito(client):
    assert _upload(client, _wav()).status_code == 202


def test_upload_acima_do_limite_e_recusado_com_413(client, monkeypatch):
    monkeypatch.setenv("MAX_UPLOAD_MB", "1")
    get_settings.cache_clear()

    resposta = _upload(client, b"RIFF" + b"\x00" * (2 * 1024 * 1024))

    assert resposta.status_code == 413
    assert "limite" in resposta.json()["detail"].lower()


def test_upload_recusado_nao_deixa_job_na_fila(client, monkeypatch):
    """O job é criado só depois da gravação: um upload recusado não pode
    deixar trabalho órfão para o worker pegar."""
    from app.repositories.job_repository import get_job_repository

    monkeypatch.setenv("MAX_UPLOAD_MB", "1")
    get_settings.cache_clear()
    _upload(client, b"RIFF" + b"\x00" * (2 * 1024 * 1024))

    assert get_job_repository().next_queued() is None


def test_arquivo_parcial_e_removido_ao_estourar_o_limite(tmp_path):
    """Upload recusado não pode deixar lixo ocupando disco."""
    repo = StorageRepository(tmp_path)
    origem = io.BytesIO(b"x" * (3 * 1024 * 1024))

    with pytest.raises(ArquivoGrandeDemaisError):
        repo.save_audio_stream("job-1", origem, "reuniao.wav", max_bytes=1024 * 1024)

    assert repo.audio_path("job-1") is None
    assert not list((tmp_path / "jobs" / "job-1").glob("audio.*"))


def test_amostra_de_voz_acima_do_limite_e_recusada_com_413(client, monkeypatch):
    monkeypatch.setenv("MAX_VOICE_SAMPLE_MB", "1")
    get_settings.cache_clear()

    resposta = client.post(
        "/participants/p1/voice-samples",
        files={"file": ("amostra.wav", b"RIFF" + b"\x00" * (2 * 1024 * 1024), "audio/wav")},
        data={"name": "Leandro"},
    )

    assert resposta.status_code == 413
