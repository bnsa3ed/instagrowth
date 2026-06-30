"""Application settings — secrets + runtime config loaded from env (pydantic-settings).

Secrets are never logged or printed. In production prefer Docker secrets / Supabase Vault;
this module reads them from the environment / `.env`.
"""
from __future__ import annotations

from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # ── Supabase / Postgres ──────────────────────────────────────────────────────
    supabase_db_url: str = Field("", description="postgresql:// DSN for psycopg")
    supabase_url: str = Field("", description="https://<project>.supabase.co")
    supabase_service_role_key: str = Field("", description="service_role key (server-side only)")

    # ── Meta / Instagram ─────────────────────────────────────────────────────────
    ig_user_id: str = Field("", description="IG Business account id")
    meta_token: str = Field("", description="System User token (preferred, non-expiring)")
    ig_api_version: str = Field("v25.0", description="Graph API version")

    # ── Google Gemini ────────────────────────────────────────────────────────────
    gemini_api_key: str = Field("")
    gemini_model_primary: str = Field("gemini-3.5-flash")
    gemini_model_fallback: str = Field("gemini-3.1-flash-lite")

    # ── Telegram + Email ─────────────────────────────────────────────────────────
    telegram_bot_token: str = Field("")
    telegram_chat_id: str = Field("")
    smtp_host: str = Field("")
    smtp_port: int = Field(587)
    smtp_user: str = Field("")
    smtp_password: str = Field("")
    smtp_from: str = Field("")

    # ── Runtime ──────────────────────────────────────────────────────────────────
    account_timezone: str = Field("Africa/Cairo")
    trend_max_per_source: int = Field(30)
    log_level: str = Field("INFO")

    @property
    def graph_base(self) -> str:
        """Facebook Graph API base URL for the Facebook Login path."""
        return f"https://graph.facebook.com/{self.ig_api_version}"

    @property
    def is_configured(self) -> bool:
        """True if the minimum secrets for a live run are present."""
        return bool(self.supabase_db_url and self.meta_token and self.ig_user_id and self.gemini_api_key)


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
