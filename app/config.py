"""Application configuration loaded from environment variables.

Values can be overridden via a `.env` file (see `.env.example`) or real
environment variables. Anything not set falls back to the defaults below.
"""

from __future__ import annotations

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        env_prefix="SEO_",
        extra="ignore",
    )

    # --- App ---
    app_name: str = "AI SEO Agent"
    debug: bool = False

    # --- Scraper / HTTP ---
    # User-Agent and friends used to mimic a real browser.
    user_agent: str = (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/122.0.0.0 Safari/537.36"
    )
    request_timeout: float = 15.0  # seconds for connect+read
    max_content_bytes: int = 5_000_000  # refuse to parse bodies larger than this

    # --- Retry / backoff (for rate limiting & transient errors) ---
    max_retries: int = 4
    backoff_initial: float = 1.0  # first wait, seconds
    backoff_max: float = 30.0  # cap on any single wait, seconds
    backoff_multiplier: float = 2.0  # exponential factor

    # --- Ollama / LLM ---
    ollama_base_url: str = "http://localhost:11434"
    ollama_model: str = "llama3.2:3b"
    ollama_temperature: float = 0.2
    ollama_timeout: float = 120.0  # generation can be slow on CPU; be generous
    ollama_max_retries: int = 2  # extra attempts on timeout/connection errors

    # --- Infrastructure ---
    redis_url: str = "redis://localhost:6379/0"
    api_url: str = "http://localhost:8000"

    # --- Caching ---
    # Backend: "sqlite" (default, zero-config local file), "redis", or "none".
    cache_backend: str = "sqlite"
    cache_ttl_seconds: int = 86_400  # 24 hours
    cache_path: str = "audit_cache.sqlite3"  # used when backend == "sqlite"

    # --- Agent / ReAct loop ---
    agent_max_steps: int = 8  # hard cap on tool-use iterations
    agent_temperature: float = 0.1  # low temp = more deterministic tool choices
    agent_observation_char_limit: int = 4000  # truncate tool output fed back to LLM


@lru_cache
def get_settings() -> Settings:
    """Return a cached Settings instance (read once per process)."""
    return Settings()
