"""All settings in one place, read from environment variables / backend/.env.

Model names live here so they can be swapped without touching code.
"""

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_DIR = Path(__file__).resolve().parents[1]
ENV_FILE = BACKEND_DIR / ".env"


def _resolve(path: str) -> Path:
    p = Path(path)
    return p if p.is_absolute() else BACKEND_DIR / p


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=ENV_FILE, extra="ignore")

    # LLM (OpenRouter). Keep the default model cheap.
    openrouter_api_key: str = ""
    # Fast, cheap, no long "thinking" (~5 s, ~0.1 cent per request in tests).
    llm_model: str = "google/gemini-2.5-flash-lite"
    llm_temperature: float = 0.8
    # Thinking models spend ~3-4k tokens on reasoning before answering; a low
    # limit cuts the answer off (empty response). Only used tokens are billed.
    llm_max_tokens: int = 12000
    llm_timeout_seconds: float = 90
    max_repair_attempts: int = 5
    # OpenRouter reasoning effort ("low" / "medium" / "high"). Empty = model default.
    # Lower = faster and cheaper answers from "thinking" models.
    llm_reasoning_effort: str = ""
    # Model for fridge photos (must accept images). Empty = same as llm_model.
    vision_model: str = ""
    # Model for the one-off recipe import (data/recipes.jsonl was built with it).
    ingest_model: str = "minimax/minimax-m3"

    # Shown to OpenRouter (attribution headers).
    app_url: str = "https://code-a-cuisine-three.vercel.app"
    app_title: str = "Code a Cuisine"

    # Comma-separated list of frontend origins allowed by CORS.
    allowed_origins: str = "http://localhost:5173,http://127.0.0.1:5173"

    # Vector index (ChromaDB) and the recipe file it is built from.
    # Relative paths are resolved against the backend/ folder.
    chroma_dir: str = "data/chroma"
    recipes_file: str = "data/recipes.jsonl"

    # Redis for rate-limit counters. Empty = in-memory (local dev).
    redis_url: str = ""

    # Rate limits (same defaults as the old Vercel function).
    ratelimit_per_ip_daily: int = 15
    ratelimit_per_ip_burst: int = 5  # per 60 seconds
    ratelimit_global_daily: int = 300
    # Fridge photos have their own (smaller) budget.
    ratelimit_photo_per_ip_daily: int = 10
    ratelimit_photo_per_ip_burst: int = 3
    ratelimit_photo_global_daily: int = 150

    # Remote MCP server (mcp_server/http.py)
    mcp_api_keys: str = ""  # comma-separated; empty = MCP endpoint rejects everything
    mcp_allowed_hosts: str = "localhost:*,127.0.0.1:*"  # Host headers accepted (add your domain)
    mcp_allowed_origins: str = ""  # browser Origins accepted (MCP clients usually send none)
    mcp_ratelimit_per_key_daily: int = 500
    mcp_ratelimit_per_key_burst: int = 60  # per 60 seconds
    mcp_ratelimit_global_daily: int = 3000

    @property
    def chroma_path(self) -> Path:
        return _resolve(self.chroma_dir)

    @property
    def recipes_path(self) -> Path:
        return _resolve(self.recipes_file)

    @property
    def origins(self) -> list[str]:
        return [o.strip().rstrip("/") for o in self.allowed_origins.split(",") if o.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
