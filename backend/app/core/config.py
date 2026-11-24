from functools import lru_cache
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict

_DEFAULT_DEV_SECRET = "dev-insecure-secret-change-in-production-32bytes"


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    app_env: str = "development"
    app_name: str = "AI SDR"
    app_slug: str = "ai-sdr"
    api_v1_prefix: str = "/api/v1"
    log_level: str = "INFO"
    cors_origins: str = "http://localhost:5173,http://localhost:3000"

    database_url: str = "sqlite+aiosqlite:///./ai_sdr.db"

    llm_default_provider: Literal["mock", "ollama", "gemini"] = "mock"
    llm_fallback_providers: str = "ollama,gemini,mock"
    llm_redact_pii_for_cloud: bool = True

    auth_secret_key: str = _DEFAULT_DEV_SECRET

    @property
    def cors_origin_list(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return cached application settings."""
    return Settings()


def clear_settings_cache() -> None:
    """Clear cached settings for deterministic test overrides."""
    get_settings.cache_clear()


def validate_production_security(settings: Settings) -> None:
    """Fail fast at startup if insecure defaults remain active in production."""
    if settings.app_env.strip().lower() != "production":
        return

    errors: list[str] = []
    if settings.auth_secret_key == _DEFAULT_DEV_SECRET or len(settings.auth_secret_key) < 32:
        errors.append(
            "AUTH_SECRET_KEY must be overridden with a unique >=32-byte secret in production."
        )
    if "*" in settings.cors_origin_list:
        errors.append("CORS_ORIGINS must not contain wildcard '*' in production.")
    if errors:
        raise RuntimeError("Production security validation failed: " + " | ".join(errors))
