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

    voice_model: str = Field(default="speechbrain/spkrec-ecapa-voxceleb", alias="VOICE_MODEL")
    voice_identification_threshold: float = Field(default=0.30, alias="VOICE_IDENTIFICATION_THRESHOLD")
    voice_min_margin: float = Field(default=0.05, alias="VOICE_MIN_MARGIN")
    voice_outlier_threshold: float = Field(default=0.45, alias="VOICE_OUTLIER_THRESHOLD")

    ollama_base_url: str = Field(default="http://127.0.0.1:11434", alias="OLLAMA_BASE_URL")
    ollama_model: str = Field(default="qwen3:14b", alias="OLLAMA_MODEL")

    enable_implicit_refinement: bool = Field(default=False, alias="ENABLE_IMPLICIT_REFINEMENT")
    demo_mode: bool = Field(default=False, alias="DEMO_MODE")


@lru_cache
def get_settings() -> Settings:
    return Settings()
