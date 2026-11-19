import re
from email.utils import parseaddr
from functools import lru_cache
from typing import Literal
from urllib.parse import urlsplit

from pydantic import Field, PostgresDsn, SecretStr, model_validator
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


HEADER_NAME_PATTERN = re.compile(r"[a-z0-9!#$%&'*+.^_`|~-]+")
FORWARDING_CHAIN_HEADERS = frozenset({"x-forwarded-for", "forwarded", "x-forwarded-host"})

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
    # Name of ONE request header carrying the real client IP, set by a trusted edge proxy that
    # overwrites any client-supplied value (Render: "cf-connecting-ip"). Unset by default: the
    # TCP peer address is used. Enabling it is a deployment trust assumption; see DEPLOYMENT.md.
    trusted_client_ip_header: str | None = Field(default=None, alias="TRUSTED_CLIENT_IP_HEADER")
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
    email_backend: Literal["console", "smtp", "resend", "disabled"] = Field(
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
    resend_api_key: SecretStr | None = Field(default=None, alias="RESEND_API_KEY")
    resend_timeout_seconds: float = Field(
        default=10.0, gt=0, le=60, alias="RESEND_TIMEOUT_SECONDS"
    )
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
    # v0.8.2: whether accepting an invite may give a user a second active membership. Keep it
    # off until the frontend organization switcher ships and a rollback build that supports
    # organization selection exists: the v0.8.1 rollback build locks multi-membership users out.
    multi_organization_memberships_enabled: bool = Field(
        default=False, alias="MULTI_ORGANIZATION_MEMBERSHIPS_ENABLED"
    )

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        # Validation errors must never echo configuration values (secrets, DSNs) to logs.
        hide_input_in_errors=True,
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
    def validate_trusted_client_ip_header(self) -> "Settings":
        if self.trusted_client_ip_header is None:
            return self
        header = self.trusted_client_ip_header.strip().lower()
        if not header:
            self.trusted_client_ip_header = None
            return self
        if not HEADER_NAME_PATTERN.fullmatch(header):
            raise ValueError("TRUSTED_CLIENT_IP_HEADER must be a single HTTP header name.")
        if header in FORWARDING_CHAIN_HEADERS:
            # Multi-hop headers are client-appendable chains; the leftmost entry is spoofable.
            raise ValueError(
                "TRUSTED_CLIENT_IP_HEADER must name a single-value header set by the edge proxy "
                "(for example cf-connecting-ip), never a forwarding chain."
            )
        self.trusted_client_ip_header = header
        return self

    @model_validator(mode="after")
    def validate_email_settings(self) -> "Settings":
        if self.email_backend == "smtp" and not self.smtp_host:
            raise ValueError("SMTP_HOST is required when EMAIL_BACKEND=smtp.")
        if self.smtp_use_ssl and self.smtp_use_tls:
            raise ValueError("SMTP_USE_SSL and SMTP_USE_TLS cannot both be enabled.")
        if self.email_backend == "resend":
            self._validate_resend_settings()
        if self.is_production and self.email_backend in {"smtp", "resend"}:
            parsed = urlsplit(self.frontend_base_url)
            if parsed.scheme != "https" or parsed.hostname in {None, "localhost", "127.0.0.1"}:
                raise ValueError(
                    "Production email delivery requires FRONTEND_BASE_URL to be the public "
                    "HTTPS frontend origin."
                )
        return self

    def _validate_resend_settings(self) -> None:
        key = self.resend_api_key.get_secret_value().strip() if self.resend_api_key else ""
        if not key:
            raise ValueError("RESEND_API_KEY is required when EMAIL_BACKEND=resend.")
        if any(char.isspace() for char in key) or not key.isprintable():
            raise ValueError("RESEND_API_KEY must be a single API key value.")
        self.resend_api_key = SecretStr(key)
        sender = self.email_from.strip()
        _, address = parseaddr(sender)
        domain = address.rpartition("@")[2].lower()
        if (
            not address
            or "@" not in address
            or not domain
            or any(char in sender for char in "\r\n")
        ):
            raise ValueError(
                "EMAIL_FROM must be a sender such as 'AgentHQ <no-reply@example.com>' "
                "when EMAIL_BACKEND=resend."
            )
        if self.is_production and (domain.endswith(".local") or "." not in domain):
            raise ValueError(
                "Production EMAIL_FROM must use a domain verified in Resend, not the "
                "development default."
            )
        self.email_from = sender

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
