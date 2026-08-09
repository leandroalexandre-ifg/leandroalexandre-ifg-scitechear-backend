import io
import wave
from pathlib import Path

import pytest
import torch
from fastapi.testclient import TestClient

from app.config import get_settings
from app.main import app
from app.services import voice_service


@pytest.fixture
def client() -> TestClient:
    return TestClient(app)


@pytest.fixture
def wav_bytes() -> bytes:
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as wav_file:
        wav_file.setnchannels(1)
        wav_file.setsampwidth(2)
        wav_file.setframerate(16000)
        wav_file.writeframes(b"\x00\x00" * 1600)  # ~0.1s de silêncio, 16 kHz mono
    return buffer.getvalue()


@pytest.fixture(autouse=True)
def tmp_storage_root(tmp_path, monkeypatch):
    """Isola cada teste em um STORAGE_ROOT descartável — nenhum teste escreve
    no ./storage real do repositório."""
    monkeypatch.setenv("STORAGE_ROOT", str(tmp_path))
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.fixture(autouse=True)
def stub_voice_embedding(monkeypatch):
    """Evita baixar/rodar o modelo real do SpeechBrain nos testes: substitui a
    extração por um embedding determinístico derivado do conteúdo do arquivo
    (mesma dimensão do ECAPA-TDNN, 192). Ver CLAUDE.md: "prefira testes de
    contrato com fixtures a rodar GPU no ciclo de desenvolvimento"."""

    def _fake_extrair_embedding(caminho_wav) -> torch.Tensor:
        content = Path(caminho_wav).read_bytes()
        seed = sum(content) % (2**31)
        generator = torch.Generator().manual_seed(seed)
        return torch.rand(192, generator=generator)

    monkeypatch.setattr(voice_service, "extrair_embedding", _fake_extrair_embedding)
    yield
