"""
config.py — Application settings, loaded from environment variables.

Loading priority (highest first):
  1. Real environment variables  — injected by the platform (Render/HF/systemd)
  2. .env file                   — local dev only, never committed
  3. Default value below         — only for settings safe to assume

Fields with NO default are REQUIRED — the app crashes loudly at startup if missing.
A loud crash beats silently running misconfigured.
"""

from functools import lru_cache
from typing import Literal

from pydantic import computed_field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
  model_config = SettingsConfigDict(
    env_file='.env',
    env_file_encoding='utf-8',
    case_sensitive=True,
    extra='ignore',  # ignore leftover env keys
  )

  # ── ENVIRONMENT ─────────────────────────────────────────────────────────────
  APP_ENV: Literal['DEVELOPMENT', 'STAGING', 'PRODUCTION'] = 'DEVELOPMENT'
  LOG_LEVEL: Literal['DEBUG', 'INFO', 'WARNING', 'ERROR', 'CRITICAL'] = 'INFO'

  # ── CACHE (Redis) ───────────────────────────────────────────────────────────
  REDIS_URL: str = ''

  # ── DATABASE ────────────────────────────────────────────────────
  DATABASE_URL: str

  # ── TRACING ──────────────────────────────────────────────
  TRACELOOP_API_ENDPOINT: str

  # ── COMPUTED ────────────────────────────────────────────────────────────────
  @computed_field
  @property
  def IS_DEVELOPMENT(self) -> bool:
    return self.APP_ENV == 'DEVELOPMENT'


@lru_cache
def get_settings() -> Settings:
  return Settings()


settings = get_settings()
