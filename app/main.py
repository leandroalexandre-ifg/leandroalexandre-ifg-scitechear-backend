import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import auth, health, jobs, participants
from app.config import get_settings

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Sem isto a linha de diagnóstico abaixo nunca chega aos logs em produção:
    # o uvicorn configura só os loggers "uvicorn*", deixando o root sem
    # handler, e um registro de nível INFO que propaga até lá é descartado
    # (o lastResort do logging só emite WARNING+). O worker já faz a mesma
    # chamada em app/worker.py — sem ela aqui, a comparação lado a lado
    # descrita abaixo era impossível na prática: só metade do par aparecia.
    # Constatado no primeiro deploy real (servidor NumbERS), onde o journal
    # da API não tinha nenhuma ocorrência de "API iniciando".
    logging.basicConfig(level=logging.INFO)

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
