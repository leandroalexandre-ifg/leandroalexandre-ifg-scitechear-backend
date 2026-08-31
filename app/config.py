from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    hf_token: str = Field(default="", alias="HF_TOKEN")
    storage_root: str = Field(default="./storage", alias="STORAGE_ROOT")

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

    # AS-Norm (Adaptive Score Normalization) — método alternativo de decisão em
    # identificar_speaker, desligado por padrão. Em vez de comparar o score de
    # cosseno bruto contra um limiar fixo, normaliza o candidato pelo z-score
    # relativo ao cohort dos impostores mais parecidos no próprio banco.
    # Objetivo: separar o caso Reed/Eddy (score 0.9555, cai dentro da própria
    # faixa de match genuíno — nenhum corte de cosseno absoluto resolve isso,
    # ver docs/PENDENCIAS.md). NÃO ativar em produção antes de validação com
    # dados reais.
    enable_voice_asnorm: bool = Field(default=False, alias="ENABLE_VOICE_ASNORM")
    voice_min_absolute_score: float = Field(default=0.40, alias="VOICE_MIN_ABSOLUTE_SCORE")
    voice_zscore_threshold: float = Field(default=2.0, alias="VOICE_ZSCORE_THRESHOLD")
    voice_zscore_margin: float = Field(default=0.5, alias="VOICE_ZSCORE_MARGIN")
    voice_cohort_size: int = Field(default=3, alias="VOICE_COHORT_SIZE")

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


@lru_cache
def get_settings() -> Settings:
    return Settings()
