import logging
import re
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import auth, health, jobs, participants
from app.config import get_settings

logger = logging.getLogger(__name__)


class RedigirTokenDeQueryString(logging.Filter):
    """Impede que o JWT do WebSocket seja gravado no log de acesso.

    `/ws/{job_id}` autentica por query string porque o handshake de WebSocket
    não aceita header `Authorization` em todo cliente (ver app/api/jobs.py). O
    log de acesso do uvicorn registra o caminho COM a query, então cada conexão
    escrevia um JWT válido no journald — encontrado em 2026-09-06 no journal do
    servidor, incluindo um token ainda dentro da validade. Log não é lugar de
    credencial: quem lê o journal não precisa poder se autenticar como quem
    abriu a conexão, e o journal sobrevive por muito mais tempo que o token.

    Filtra a mensagem e os argumentos porque o uvicorn passa o caminho como
    argumento de formatação ('%s - "WebSocket %s" [accepted]'), não interpolado
    na mensagem.
    """

    _PADRAO = re.compile(r"(token=)[^\s\"&]+")

    def filter(self, record: logging.LogRecord) -> bool:
        if isinstance(record.msg, str):
            record.msg = self._redigir(record.msg)
        if isinstance(record.args, tuple):
            record.args = tuple(self._redigir(a) for a in record.args)
        elif isinstance(record.args, dict):
            record.args = {k: self._redigir(v) for k, v in record.args.items()}
        return True

    def _redigir(self, valor):
        if isinstance(valor, str) and "token=" in valor:
            return self._PADRAO.sub(r"\1REDACTED", valor)
        return valor


# A linha do WebSocket NÃO sai pelo logger "uvicorn.access", como seria
# natural supor: os três backends de WS do uvicorn
# (protocols/websockets/{websockets_impl,websockets_sansio_impl,wsproto_impl}.py)
# emitem '%s - "WebSocket %s" [accepted]' pelo logger "uvicorn.error". Supor o
# logger errado aqui é falha silenciosa: o filtro instala, os testes passam e o
# token continua indo para o journal — foi exatamente o que aconteceu na
# primeira tentativa desta correção, pega só na verificação no servidor.
_LOGGERS_QUE_REGISTRAM_A_URL = ("uvicorn.error", "uvicorn.access", "uvicorn")


def instalar_filtro_de_token() -> None:
    """Prende o filtro onde os registros com a URL realmente passam.

    Nos dois níveis, de propósito. Um filtro preso a um LOGGER só vê o que é
    registrado nele (o que propaga de um filho para um ancestral não passa
    pelos filtros do ancestral); um filtro preso a um HANDLER vê tudo que chega
    àquele handler, venha de onde vier. Como o uvicorn põe handler próprio em
    "uvicorn.error" e "uvicorn.access" e desliga a propagação, prender só na
    raiz não alcançaria nada — e prender só nos loggers deixaria passar
    qualquer emissor novo que use os mesmos handlers.
    """
    filtro = RedigirTokenDeQueryString()
    for nome in _LOGGERS_QUE_REGISTRAM_A_URL:
        logger_alvo = logging.getLogger(nome)
        logger_alvo.addFilter(filtro)
        for handler in logger_alvo.handlers:
            handler.addFilter(filtro)
    for handler in logging.getLogger().handlers:
        handler.addFilter(filtro)


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

    # Depois do basicConfig, senão a raiz ainda não tem handler onde prender o
    # filtro. Antes de servir qualquer requisição, porque o lifespan roda na
    # subida — nenhuma linha de acesso é emitida antes daqui.
    instalar_filtro_de_token()

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
