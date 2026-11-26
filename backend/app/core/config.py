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
    auto_create_tables: bool = True
    seed_demo_data: bool = False
    db_pool_size: int = 10
    db_max_overflow: int = 20
    db_pool_timeout: int = 30
    db_pool_recycle: int = 1800

    redis_url: str = ""
    celery_broker_url: str = "redis://localhost:6379/0"
    celery_result_backend: str = "redis://localhost:6379/1"
    task_execution_mode: Literal["inline", "celery"] = "inline"

    llm_default_provider: Literal["mock", "ollama", "gemini"] = "mock"
    llm_fallback_providers: str = "ollama,gemini,mock"
    ollama_base_url: str = "http://localhost:11434"
    ollama_default_model: str = "llama-3.1-8b-instruct"
    gemini_api_key: str = ""
    gemini_default_model: str = "gemini-2.5-flash"
    llm_redact_pii_for_cloud: bool = True

    embedding_provider: Literal["deterministic", "ollama"] = "deterministic"
    embedding_dimensions: int = 384

    email_provider: Literal["mock", "smtp", "resend", "sendgrid"] = "mock"
    email_from_address: str = "sdr@acme-sdr.local"
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_username: str = ""
    smtp_password: str = ""
    smtp_use_tls: bool = True
    resend_api_key: str = ""
    sendgrid_api_key: str = ""

    crm_outbound_provider: Literal["mock", "hubspot", "salesforce"] = "mock"
    hubspot_api_key: str = ""
    salesforce_instance_url: str = ""
    salesforce_access_token: str = ""

    auth_secret_key: str = _DEFAULT_DEV_SECRET
    auth_require_token: bool = False
    webhook_signing_secret: str = ""
    rate_limit_enabled: bool = False
    rate_limit_requests_per_minute: int = 120
    otel_enabled: bool = False

    @property
    def cors_origin_list(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]

    @property
    def llm_fallback_list(self) -> list[str]:
        return [item.strip() for item in self.llm_fallback_providers.split(",") if item.strip()]

    @property
    def effective_webhook_secret(self) -> str:
        return self.webhook_signing_secret.strip() or self.auth_secret_key


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
