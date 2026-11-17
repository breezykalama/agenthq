from functools import lru_cache
from typing import Literal
from urllib.parse import urlsplit

from pydantic import Field, PostgresDsn, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

DEFAULT_JWT_SECRET_KEY = "change-me-in-production-at-least-32-bytes"
WEAK_SECRET_PREFIXES = (
    "change-me",
    "changeme",
    "default",
    "password",
    "replace-me",
    "replace-with",
)


def normalize_database_url(database_url: str) -> str:
    for prefix in ("postgres://", "postgresql://"):
        if database_url.startswith(prefix):
            return database_url.replace(prefix, "postgresql+psycopg://", 1)
    return database_url


class CorsSettings(BaseSettings):
    backend_cors_origins: str = Field(default="", alias="BACKEND_CORS_ORIGINS")

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )


def get_cors_origins() -> list[str]:
    origins = CorsSettings().backend_cors_origins
    return [origin.strip().rstrip("/") for origin in origins.split(",") if origin.strip()]


class Settings(BaseSettings):
    app_name: str = "AgentHQ"
    environment: str = "development"
    database_url: PostgresDsn = Field(alias="DATABASE_URL")
    jwt_secret_key: str = Field(
        default=DEFAULT_JWT_SECRET_KEY,
        alias="JWT_SECRET_KEY",
    )
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 60
    bootstrap_secret: str | None = Field(default=None, alias="BOOTSTRAP_SECRET")
    allow_public_registration: bool | None = Field(
        default=None,
        alias="ALLOW_PUBLIC_REGISTRATION",
    )
    allow_private_mcp_urls: bool | None = Field(default=None, alias="ALLOW_PRIVATE_MCP_URLS")
    mcp_discovery_mode: Literal["mock", "real"] = Field(
        default="mock",
        alias="MCP_DISCOVERY_MODE",
    )
    rate_limits_enabled: bool = Field(default=True, alias="RATE_LIMITS_ENABLED")
    redis_url: str | None = Field(default=None, alias="REDIS_URL")
    auth_rate_limit_attempts: int = Field(default=10, ge=1, alias="AUTH_RATE_LIMIT_ATTEMPTS")
    auth_rate_limit_window_seconds: int = Field(
        default=60,
        ge=1,
        alias="AUTH_RATE_LIMIT_WINDOW_SECONDS",
    )
    sensitive_rate_limit_window_seconds: int = Field(
        default=60,
        ge=1,
        alias="SENSITIVE_RATE_LIMIT_WINDOW_SECONDS",
    )
    invite_create_rate_limit_attempts: int = Field(
        default=10,
        ge=1,
        alias="INVITE_CREATE_RATE_LIMIT_ATTEMPTS",
    )
    approval_rate_limit_attempts: int = Field(
        default=30,
        ge=1,
        alias="APPROVAL_RATE_LIMIT_ATTEMPTS",
    )
    execution_rate_limit_attempts: int = Field(
        default=60,
        ge=1,
        alias="EXECUTION_RATE_LIMIT_ATTEMPTS",
    )
    mcp_sync_rate_limit_attempts: int = Field(
        default=5,
        ge=1,
        alias="MCP_SYNC_RATE_LIMIT_ATTEMPTS",
    )
    gateway_list_rate_limit_attempts: int = Field(
        default=60,
        ge=1,
        alias="GATEWAY_LIST_RATE_LIMIT_ATTEMPTS",
    )
    gateway_call_rate_limit_attempts: int = Field(
        default=30,
        ge=1,
        alias="GATEWAY_CALL_RATE_LIMIT_ATTEMPTS",
    )
    gateway_token_rate_limit_attempts: int = Field(
        default=10,
        ge=1,
        alias="GATEWAY_TOKEN_RATE_LIMIT_ATTEMPTS",
    )
    policy_decision_rate_limit_attempts: int = Field(
        default=60,
        ge=1,
        alias="POLICY_DECISION_RATE_LIMIT_ATTEMPTS",
    )
    compliance_rate_limit_attempts: int = Field(
        default=30,
        ge=1,
        alias="COMPLIANCE_RATE_LIMIT_ATTEMPTS",
    )
    email_backend: Literal["console", "smtp", "disabled"] = Field(
        default="console",
        alias="EMAIL_BACKEND",
    )
    email_from: str = Field(default="AgentHQ <no-reply@agenthq.local>", alias="EMAIL_FROM")
    smtp_host: str | None = Field(default=None, alias="SMTP_HOST")
    smtp_port: int = Field(default=587, ge=1, le=65535, alias="SMTP_PORT")
    smtp_username: str | None = Field(default=None, alias="SMTP_USERNAME")
    smtp_password: str | None = Field(default=None, alias="SMTP_PASSWORD")
    smtp_use_tls: bool = Field(default=True, alias="SMTP_USE_TLS")
    smtp_use_ssl: bool = Field(default=False, alias="SMTP_USE_SSL")
    smtp_timeout_seconds: float = Field(default=10.0, gt=0, le=60, alias="SMTP_TIMEOUT_SECONDS")
    email_outbox_worker_enabled: bool = Field(default=True, alias="EMAIL_OUTBOX_WORKER_ENABLED")
    email_outbox_poll_seconds: float = Field(
        default=5.0, gt=0, le=300, alias="EMAIL_OUTBOX_POLL_SECONDS"
    )
    email_outbox_max_attempts: int = Field(
        default=6, ge=1, le=20, alias="EMAIL_OUTBOX_MAX_ATTEMPTS"
    )
    identity_min_response_ms: int = Field(
        default=400, ge=0, le=5000, alias="IDENTITY_MIN_RESPONSE_MS"
    )
    frontend_base_url: str = Field(default="http://localhost:5173", alias="FRONTEND_BASE_URL")

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    @property
    def sqlalchemy_database_uri(self) -> str:
        return normalize_database_url(str(self.database_url))

    @property
    def is_production(self) -> bool:
        return self.environment.strip().lower() == "production"

    @property
    def public_registration_enabled(self) -> bool:
        if self.allow_public_registration is not None:
            return self.allow_public_registration
        return not self.is_production

    @property
    def private_mcp_urls_allowed(self) -> bool:
        if self.allow_private_mcp_urls is not None:
            return self.allow_private_mcp_urls
        return not self.is_production

    @property
    def normalized_frontend_base_url(self) -> str:
        return self.frontend_base_url.rstrip("/")

    @model_validator(mode="after")
    def validate_email_settings(self) -> "Settings":
        if self.email_backend == "smtp" and not self.smtp_host:
            raise ValueError("SMTP_HOST is required when EMAIL_BACKEND=smtp.")
        if self.smtp_use_ssl and self.smtp_use_tls:
            raise ValueError("SMTP_USE_SSL and SMTP_USE_TLS cannot both be enabled.")
        if self.is_production and self.email_backend == "smtp":
            parsed = urlsplit(self.frontend_base_url)
            if parsed.scheme != "https" or parsed.hostname in {None, "localhost", "127.0.0.1"}:
                raise ValueError(
                    "Production email delivery requires FRONTEND_BASE_URL to be the public "
                    "HTTPS frontend origin."
                )
        return self

    @model_validator(mode="after")
    def validate_production_secrets(self) -> "Settings":
        if not self.is_production:
            return self

        secret = self.jwt_secret_key.strip()
        normalized_secret = secret.lower()
        if (
            not secret
            or secret == DEFAULT_JWT_SECRET_KEY
            or len(secret) < 32
            or normalized_secret.startswith(WEAK_SECRET_PREFIXES)
            or len(set(secret)) < 8
        ):
            raise ValueError(
                "Production requires a strong JWT_SECRET_KEY of at least 32 characters."
            )
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
