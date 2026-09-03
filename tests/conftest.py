import io
import wave
from pathlib import Path

import pytest
import torch
from fastapi.testclient import TestClient

from app.config import get_settings
from app.main import app
from app.repositories.job_repository import reset_job_repository
from app.repositories.user_repository import reset_user_repository
from app.services import voice_service

TEST_USER_EMAIL = "teste@scitechear.example.com"
TEST_USER_PASSWORD = "senha-de-teste-123"


@pytest.fixture
def unauthenticated_client() -> TestClient:
    """TestClient sem token — usado só pelos testes de app/api/auth.py e por
    quem precisa verificar o comportamento de rotas protegidas sem
    Authorization (401)."""
    return TestClient(app)


@pytest.fixture
def client(unauthenticated_client: TestClient) -> TestClient:
    """TestClient com um usuário de teste já registrado e logado (header
    Authorization padrão) — a maioria dos testes de contrato HTTP não é
    sobre autenticação em si, então evita repetir register+login em cada um.
    client.user_id fica disponível para testes que criam jobs/perfis direto
    pelo repository (sem passar pela rota /upload), para o user_id bater com
    o do token."""
    register = unauthenticated_client.post(
        "/auth/register",
        json={"email": TEST_USER_EMAIL, "password": TEST_USER_PASSWORD, "name": "Usuário de Teste"},
    )
    assert register.status_code == 201, register.text
    login = unauthenticated_client.post(
        "/auth/login", json={"email": TEST_USER_EMAIL, "password": TEST_USER_PASSWORD}
    )
    assert login.status_code == 200, login.text

    unauthenticated_client.headers.update({"Authorization": f"Bearer {login.json()['access_token']}"})
    unauthenticated_client.user_id = register.json()["user_id"]
    return unauthenticated_client


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
    no ./storage real do repositório. Também fixa um JWT_SECRET_KEY de teste
    (auth_service recusa emitir/validar token sem ele — ver app/config.py)."""
    monkeypatch.setenv("STORAGE_ROOT", str(tmp_path))
    # Sobrescrever STORAGE_ROOT não basta: database_url_efetivo (app/config.py)
    # só deriva o caminho do banco a partir dele quando DATABASE_URL está
    # vazio — preenchido, DATABASE_URL vence e o isolamento acima vira letra
    # morta. Um .env de produção com DATABASE_URL definido (o .env.example
    # convida a isso) fazia a suíte inteira ler e escrever no banco REAL:
    # sem descarte entre testes, o rate limit de /auth/register acumulava até
    # responder 429 e derrubava ~20 testes de contrato. Descoberto no primeiro
    # deploy real (servidor NumbERS). Remover a variável do ambiente do teste
    # força a derivação a partir do tmp_path, independentemente do .env.
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setenv("JWT_SECRET_KEY", "chave-de-teste-nao-usar-em-producao")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.fixture(autouse=True)
def stub_voice_embedding(monkeypatch):
    """Evita baixar/rodar o modelo real do SpeechBrain nos testes: substitui a
    extração por um embedding determinístico derivado do conteúdo do arquivo
    (mesma dimensão do ECAPA-TDNN, 192). Ver AGENTS.md: "prefira testes de
    contrato com fixtures a rodar GPU no ciclo de desenvolvimento"."""

    def _fake_extrair_embedding(caminho_wav) -> torch.Tensor:
        content = Path(caminho_wav).read_bytes()
        seed = sum(content) % (2**31)
        generator = torch.Generator().manual_seed(seed)
        return torch.rand(192, generator=generator)

    monkeypatch.setattr(voice_service, "extrair_embedding", _fake_extrair_embedding)
    yield


@pytest.fixture(autouse=True)
def reset_job_repository_singleton(tmp_storage_root):
    """get_job_repository() é um singleton compartilhado entre requisições
    (precisa sobreviver entre POST /upload e GET /status) — mas isso não pode
    vazar estado de um teste para o outro. Descarta o singleton (não só os
    dados): a implementação em banco fixa a conexão a um arquivo dentro do
    STORAGE_ROOT no momento da criação, então precisa ser recriada a cada
    teste para acompanhar o tmp_path isolado de `tmp_storage_root` (daí a
    dependência explícita — precisa rodar depois dele)."""
    reset_job_repository()
    yield
    reset_job_repository()


@pytest.fixture(autouse=True)
def reset_user_repository_singleton(tmp_storage_root):
    """Mesmo raciocínio de reset_job_repository_singleton acima, para o
    singleton de UserRepository (mesmo arquivo SQLite, mesma necessidade de
    não vazar estado — nem conexão presa ao tmp_path de um teste anterior —
    entre testes)."""
    reset_user_repository()
    yield
    reset_user_repository()
