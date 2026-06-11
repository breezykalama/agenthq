from functools import lru_cache

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
