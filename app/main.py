import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import auth, health, jobs, participants
from app.config import get_settings

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Defesa em profundidade para a fragilidade de STORAGE_ROOT (item 4 da
    # preparação para produção, ver app/config.py): mesmo com a resolução
    # já corrigida na fonte, logar os caminhos absolutos efetivos na subida
    # deixa um operador notar visualmente se API e worker (app/worker.py,
    # processo separado) alguma vez divergirem — mesmo formato de linha nos
    # dois, para comparação lado a lado nos logs.
    settings = get_settings()
    logger.info("API iniciando — STORAGE_ROOT=%s DATABASE_URL=%s", settings.storage_root, settings.database_url_efetivo)
    yield


app = FastAPI(title="SciTech Ear — Backend", version="0.1.0", lifespan=lifespan)

# CORS de desenvolvimento: libera o Android Emulator / túnel durante a integração.
# Restringir origens antes de qualquer deploy fora do ambiente de testes.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(health.router)
app.include_router(auth.router)
app.include_router(jobs.router)
app.include_router(participants.router)
