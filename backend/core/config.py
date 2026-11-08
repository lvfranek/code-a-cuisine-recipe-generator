"""All settings in one place, read from environment variables / backend/.env.

Model names live here so they can be swapped without touching code.
"""

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

ENV_FILE = Path(__file__).resolve().parents[1] / ".env"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=ENV_FILE, extra="ignore")

    # LLM (OpenRouter). Keep the default model cheap.
    openrouter_api_key: str = ""
    llm_model: str = "minimax/minimax-m3"
    llm_temperature: float = 0.8
    llm_max_tokens: int = 6000
    llm_timeout_seconds: float = 90
    max_repair_attempts: int = 5
    # Model for the one-off recipe import. Empty = same as llm_model.
    ingest_model: str = ""

    # Shown to OpenRouter (attribution headers).
    app_url: str = "https://code-a-cuisine-three.vercel.app"
    app_title: str = "Code a Cuisine"

    # Comma-separated list of frontend origins allowed by CORS.
    allowed_origins: str = "http://localhost:5173,http://127.0.0.1:5173"

    # Redis for rate-limit counters. Empty = in-memory (local dev).
    redis_url: str = ""

    # Rate limits (same defaults as the old Vercel function).
    ratelimit_per_ip_daily: int = 15
    ratelimit_per_ip_burst: int = 5  # per 60 seconds
    ratelimit_global_daily: int = 300

    @property
    def origins(self) -> list[str]:
        return [o.strip().rstrip("/") for o in self.allowed_origins.split(",") if o.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
