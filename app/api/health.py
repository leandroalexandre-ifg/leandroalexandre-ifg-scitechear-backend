from fastapi import APIRouter

router = APIRouter(tags=["health"])


@router.get("/health")
async def health() -> dict:
    return {"status": "ok"}


@router.get("/ready")
async def ready() -> dict:
    # Fase 1: contrato HTTP apenas, sem PipelineFacade nem modelos carregados.
    # Passa a refletir prontidão real de worker/modelos/GPU a partir da Fase 6.
    return {
        "ready": False,
        "detail": "Pipeline de IA ainda não implementado (stub da Fase 1).",
    }
