import requests
import torch
from fastapi import APIRouter

from app.config import get_settings

router = APIRouter(tags=["health"])


@router.get("/health")
async def health() -> dict:
    return {"status": "ok"}


def _ollama_disponivel(base_url: str, timeout: float = 2.0) -> bool:
    try:
        response = requests.get(f"{base_url}/api/tags", timeout=timeout)
        return response.ok
    except requests.RequestException:
        return False


@router.get("/ready")
def ready() -> dict:
    """Prontidão real de dependências EXTERNAS — não confundir com "modelos
    carregados": WhisperX/pyannote/SpeechBrain continuam lazy, carregados sob
    demanda por job (ver app/services/*). Aqui checamos o que precisa estar
    disponível ANTES de aceitar um job real: HF_TOKEN configurado (pyannote é
    um modelo gated) e o Ollama respondendo (LLM das perguntas). `ready` só é
    True quando as duas checagens passam — nunca incondicional.

    `def` síncrona de propósito: a checagem do Ollama é uma chamada de rede
    bloqueante; como rota síncrona, o FastAPI despacha para threadpool em vez
    de travar o event loop (equivalente a `async def` + `run_in_threadpool`).
    """
    settings = get_settings()

    checks = {
        "hf_token_configurado": bool(settings.hf_token),
        "ollama_disponivel": _ollama_disponivel(settings.ollama_base_url),
    }
    tudo_ok = all(checks.values())

    return {
        "ready": tudo_ok,
        "checks": checks,
        "gpu_disponivel": torch.cuda.is_available(),
        "detail": (
            "Dependências externas disponíveis; modelos ML continuam carregados sob demanda por job."
            if tudo_ok
            else "Alguma dependência externa indisponível — ver 'checks'."
        ),
    }
