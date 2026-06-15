"""Centralized configuration using Pydantic BaseSettings."""
from functools import lru_cache
from typing import Optional
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # Required
    groq_api_key: str = Field(default="", alias="GROQ_API_KEY")

    # LLM
    groq_model: str = Field(default="llama-3.3-70b-versatile", alias="GROQ_MODEL")
    cerebras_api_key: str = Field(default="", alias="CEREBRAS_API_KEY")
    openrouter_api_key: str = Field(default="", alias="OPENROUTER_API_KEY")
    ollama_url: str = Field(default="http://localhost:11434/v1/chat/completions", alias="OLLAMA_URL")
    friday_llm_provider: str = Field(default="", alias="FRIDAY_LLM_PROVIDER")
    friday_enable_ollama: bool = Field(default=False, alias="FRIDAY_ENABLE_OLLAMA")

    # TTS
    tts_backend: str = Field(default="kokoro", alias="FRIDAY_TTS_BACKEND")
    friday_voice: str = Field(default="bf_emma", alias="FRIDAY_VOICE")
    friday_tts_speed: float = Field(default=1.1, alias="FRIDAY_TTS_SPEED")
    kokoro_model_path: str = Field(default="kokoro-v1.0.onnx", alias="KOKORO_MODEL_PATH")
    kokoro_voices_path: str = Field(default="voices-v1.0.bin", alias="KOKORO_VOICES_PATH")

    # STT
    whisper_model: str = Field(default="small", alias="FRIDAY_WHISPER_MODEL")
    whisper_device: str = Field(default="cpu", alias="FRIDAY_WHISPER_DEVICE")
    whisper_compute: str = Field(default="int8", alias="FRIDAY_WHISPER_COMPUTE")

    # Memory
    memory_min_importance: float = Field(default=0.4, alias="FRIDAY_MEMORY_MIN_IMPORTANCE")
    enable_memory: bool = Field(default=True, alias="FRIDAY_ENABLE_MEMORY")

    # Supabase
    supabase_url: str = Field(default="", alias="SUPABASE_URL")
    supabase_key: str = Field(default="", alias="SUPABASE_KEY")
    supabase_anon_key: str = Field(default="", alias="SUPABASE_ANON_KEY")
    supabase_auth_enabled: bool = Field(default=False, alias="FRIDAY_SUPABASE_AUTH_ENABLED")
    full_access_emails: str = Field(default="", alias="FRIDAY_FULL_ACCESS_EMAILS")
    contact_email: str = Field(default="", alias="FRIDAY_CONTACT_EMAIL")

    # Server
    allowed_origins: str = Field(default="http://localhost:8080,http://127.0.0.1:8080", alias="FRIDAY_ALLOWED_ORIGINS")
    api_key: str = Field(default="", alias="FRIDAY_API_KEY")
    log_json: bool = Field(default=False, alias="LOG_JSON")
    ui_version: str = Field(default="v4.4.0", alias="FRIDAY_UI_VERSION")

    # Weather
    lat: float = Field(default=28.6, alias="FRIDAY_LAT")
    lon: float = Field(default=77.2, alias="FRIDAY_LON")

    @property
    def full_access_email_set(self) -> set[str]:
        return {e.strip().lower() for e in self.full_access_emails.split(",") if e.strip()}

    @property
    def allowed_origins_list(self) -> list[str]:
        return [o.strip() for o in self.allowed_origins.split(",") if o.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()