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


def configurar_cors(app: FastAPI, settings) -> None:
    """CORS a partir de CORS_ALLOW_ORIGINS (default "*", o comportamento de
    desenvolvimento: Android Emulator / túnel durante a integração).

    `allow_credentials` acompanha a origem em vez de ser fixo em True: com
    origem "*", devolver `Access-Control-Allow-Credentials: true` é a
    combinação que a própria especificação de CORS proíbe, e que o Starlette
    contorna ecoando a origem de quem pediu — o que na prática libera
    credenciais para QUALQUER site. Nada aqui depende disso: a autenticação
    é por `Authorization: Bearer`, não por cookie, e o app Android é cliente
    nativo (não manda Origin, não é afetado por CORS). Com uma lista
    explícita de origens, `allow_credentials` volta a ser seguro e é ligado.

    Ver docs/DEPLOY.md para a recomendação de produção."""
    origens = settings.cors_allow_origins_list
    liberado_para_todos = "*" in origens
    app.add_middleware(
        CORSMiddleware,
        allow_origins=origens,
        allow_credentials=not liberado_para_todos,
        allow_methods=["*"],
        allow_headers=["*"],
    )


configurar_cors(app, get_settings())

app.include_router(health.router)
app.include_router(auth.router)
app.include_router(jobs.router)
app.include_router(participants.router)
