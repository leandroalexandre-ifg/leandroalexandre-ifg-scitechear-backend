from functools import lru_cache
from pathlib import Path
from typing import Optional

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# Âncora para resolver STORAGE_ROOT relativo (ver validador abaixo) — a raiz
# do repositório, não o cwd do processo. app/config.py -> .parent = app/ ->
# .parent.parent = raiz (onde storage/ vive por convenção). Assume que o
# backend roda a partir de um checkout do repositório (uvicorn app.main:app
# na raiz), o modelo de deploy já documentado do projeto — não instalado
# como pacote em site-packages.
_PROJECT_ROOT = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    # env_file ancorado em _PROJECT_ROOT, não ao cwd do processo — mesma
    # causa raiz do STORAGE_ROOT abaixo, mas potencialmente pior: se
    # ".env" relativo não resolvesse (processo iniciado de outro cwd), o
    # carregamento falha em silêncio e TODAS as configs voltam ao default
    # (não só storage_root) — ex.: JWT_SECRET_KEY vazio, quebrando auth só
    # na hora de assinar/validar um token. Achado durante a verificação
    # manual deste item, confirmado incluir na mesma correção.
    model_config = SettingsConfigDict(
        env_file=str(_PROJECT_ROOT / ".env"), env_file_encoding="utf-8", extra="ignore"
    )

    hf_token: str = Field(default="", alias="HF_TOKEN")
    storage_root: str = Field(default="./storage", alias="STORAGE_ROOT")

    @field_validator("storage_root")
    @classmethod
    def _resolver_storage_root(cls, valor: str) -> str:
        """Item 4 da preparação para produção: STORAGE_ROOT relativo
        resolvia contra o cwd do processo no momento em que ele iniciava —
        inofensivo com um processo só, mas desde o worker dedicado (item 2)
        existem dois processos que precisam concordar sobre onde o storage
        está fisicamente. Se cada um iniciar de um cwd diferente (erro de
        config no systemd, alguém rodando um dos dois manualmente de outra
        pasta), os dois passam a operar sobre diretórios físicos diferentes
        — sem erro, só arquivos "sumindo" da perspectiva de um processo e
        não do outro. Isso também afeta o DATABASE_URL default (deriva
        deste valor, ver database_url_efetivo abaixo).

        Corrigido eliminando a dependência do cwd por completo: um valor
        relativo é ancorado a _PROJECT_ROOT (fixo, baseado em Path(__file__),
        nunca no cwd) em vez do cwd do processo. Um valor já absoluto (ex.:
        configuração explícita de produção) passa direto, sem tocar em
        symlink nenhum — zero mudança de comportamento pra quem já configura
        um caminho absoluto."""
        caminho = Path(valor)
        if caminho.is_absolute():
            return valor
        return str((_PROJECT_ROOT / caminho).resolve())

    # Persistência de job_repository.py. Vazio (default) usa SQLite num
    # arquivo dentro de STORAGE_ROOT — zero infraestrutura extra. Defina
    # explicitamente para apontar a outro arquivo, ou (futuro) outro banco
    # via URL do SQLAlchemy (ex.: postgresql://...), sem mudar código.
    database_url: Optional[str] = Field(default=None, alias="DATABASE_URL")

    @property
    def database_url_efetivo(self) -> str:
        if self.database_url:
            return self.database_url
        return f"sqlite:///{Path(self.storage_root) / 'jobs.db'}"

    # app/worker.py: intervalo de polling da fila (segundos) quando não há
    # job em queued. Curto o suficiente pra não atrasar percebivelmente um
    # pipeline que leva minutos, sem ficar consultando o banco sem parar.
    worker_poll_interval_seconds: float = Field(default=2.0, alias="WORKER_POLL_INTERVAL_SECONDS")
    # Proteção contra "job veneno": quantas vezes um job pode ser encontrado
    # órfão (deixado por uma instância do worker que morreu no meio do
    # processamento) antes de parar de reenfileirar e ir direto para error.
    # Ver JobRepository.requeue_orfaos().
    worker_max_attempts_before_error: int = Field(default=3, alias="WORKER_MAX_ATTEMPTS_BEFORE_ERROR")

    # WS /ws/{job_id}: de quanto em quanto tempo a API relê o job no banco
    # para empurrar mudanças ao app. O worker roda em outro processo, então
    # o banco é o único ponto de encontro — ver o docstring de
    # job_progress_ws em app/api/jobs.py. Mais curto que o polling do worker
    # porque aqui a latência é percebida pelo usuário na tela.
    ws_poll_interval_seconds: float = Field(default=1.0, alias="WS_POLL_INTERVAL_SECONDS")
    # Teto de vida de uma conexão WebSocket: um job travado num estado
    # intermediário não deve segurar a conexão para sempre. Ao estourar, a
    # API fecha e o app volta ao polling (que continua sendo o fallback).
    ws_max_duration_seconds: float = Field(default=3600.0, alias="WS_MAX_DURATION_SECONDS")

    whisperx_model: str = Field(default="turbo", alias="WHISPERX_MODEL")
    whisperx_language: str = Field(default="pt", alias="WHISPERX_LANGUAGE")
    whisperx_batch_size: int = Field(default=16, alias="WHISPERX_BATCH_SIZE")

    diarization_model: str = Field(
        default="pyannote/speaker-diarization-community-1", alias="DIARIZATION_MODEL"
    )
    # Substituem os MIN_SPEAKERS=4/MAX_SPEAKERS=7 fixos do legado — defaults
    # calibráveis, usados quando o job não pede um número exato de falantes.
    diarization_min_speakers: int = Field(default=1, alias="DIARIZATION_MIN_SPEAKERS")
    diarization_max_speakers: int = Field(default=10, alias="DIARIZATION_MAX_SPEAKERS")

    voice_model: str = Field(default="speechbrain/spkrec-ecapa-voxceleb", alias="VOICE_MODEL")
    # 0.75 (era 0.30) — 0.30 permitia falso positivo grave: participante nunca
    # cadastrado identificado com confiança como outra pessoa (ver
    # docs/PENDENCIAS.md). Recalibrado com dados reais de embeddings ECAPA
    # (TTS sintético, ver tests/fixtures/voice_identification_real_embeddings.json):
    # piso de match genuíno observado = 0.9157 (15 amostras, 3 pessoas), teto
    # de impostor não-outlier = 0.6214 (6 amostras). 0.75 fica no meio dessa
    # folga, mais perto do piso genuíno por design (falso negativo é preferível
    # a falso positivo). PROVISÓRIO: calibrado só com TTS, pendente de
    # revalidação com gravações humanas reais antes de produção.
    voice_identification_threshold: float = Field(default=0.75, alias="VOICE_IDENTIFICATION_THRESHOLD")
    voice_min_margin: float = Field(default=0.05, alias="VOICE_MIN_MARGIN")
    voice_outlier_threshold: float = Field(default=0.45, alias="VOICE_OUTLIER_THRESHOLD")

    ollama_base_url: str = Field(default="http://127.0.0.1:11434", alias="OLLAMA_BASE_URL")
    ollama_model: str = Field(default="qwen3:14b", alias="OLLAMA_MODEL")

    # Desliga a ETAPA inteira de perguntas implícitas (não o refinador acima
    # — esse já fica de fora por padrão). Temporário: isola o comportamento
    # do sistema enquanto a qualidade da extração implícita (confabulação)
    # é validada separadamente (ver docs/PENDENCIAS.md). Sumarização também
    # é pulada quando desligado — ela só existe como insumo interno para as
    # implícitas, não tem outro consumidor.
    enable_implicit_questions: bool = Field(default=False, alias="ENABLE_IMPLICIT_QUESTIONS")
    enable_implicit_refinement: bool = Field(default=False, alias="ENABLE_IMPLICIT_REFINEMENT")
    demo_mode: bool = Field(default=False, alias="DEMO_MODE")

    # Autenticação (item 3 da preparação para produção). Vazio por padrão só
    # para não quebrar `Settings()` sem .env em dev/teste — auth_service exige
    # um valor não-vazio antes de assinar qualquer token (ver checagem em
    # app/services/auth_service.py). Gerar em produção com `openssl rand -hex 32`.
    jwt_secret_key: str = Field(default="", alias="JWT_SECRET_KEY")
    jwt_algorithm: str = Field(default="HS256", alias="JWT_ALGORITHM")
    jwt_access_token_expire_minutes: int = Field(default=30, alias="JWT_ACCESS_TOKEN_EXPIRE_MINUTES")
    jwt_refresh_token_expire_days: int = Field(default=30, alias="JWT_REFRESH_TOKEN_EXPIRE_DAYS")

    # Rate limiting de /auth/login (por e-mail) e /auth/register (por IP) —
    # ver app/services/auth_service.py e docs/BACKEND_ARCHITECTURE.md.
    auth_login_max_attempts: int = Field(default=5, alias="AUTH_LOGIN_MAX_ATTEMPTS")
    auth_login_window_minutes: int = Field(default=15, alias="AUTH_LOGIN_WINDOW_MINUTES")
    auth_login_lockout_minutes: int = Field(default=15, alias="AUTH_LOGIN_LOCKOUT_MINUTES")
    auth_register_max_attempts: int = Field(default=10, alias="AUTH_REGISTER_MAX_ATTEMPTS")
    auth_register_window_minutes: int = Field(default=60, alias="AUTH_REGISTER_WINDOW_MINUTES")


@lru_cache
def get_settings() -> Settings:
    return Settings()
