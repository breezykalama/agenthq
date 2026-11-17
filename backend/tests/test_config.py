import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.core.config import (
    DEFAULT_JWT_SECRET_KEY,
    Settings,
    get_cors_origins,
    get_settings,
    normalize_database_url,
)
from app.main import create_app


def test_normalize_database_url_for_psycopg() -> None:
    assert (
        normalize_database_url("postgresql://user:password@host/database")
        == "postgresql+psycopg://user:password@host/database"
    )
    assert (
        normalize_database_url("postgres://user:password@host/database")
        == "postgresql+psycopg://user:password@host/database"
    )


def test_get_cors_origins(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(
        "BACKEND_CORS_ORIGINS",
        "https://agenthq.example.com, https://preview.example.com/",
    )

    assert get_cors_origins() == [
        "https://agenthq.example.com",
        "https://preview.example.com",
    ]


@pytest.mark.parametrize(
    "secret",
    [
        DEFAULT_JWT_SECRET_KEY,
        "",
        "short-secret",
        "password-password-password-password",
        "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
    ],
)
def test_production_rejects_unsafe_jwt_secrets(secret: str) -> None:
    with pytest.raises(ValidationError, match="Production requires a strong JWT_SECRET_KEY"):
        Settings(
            _env_file=None,
            DATABASE_URL="postgresql://agenthq:agenthq@localhost:5432/agenthq",
            environment="production",
            JWT_SECRET_KEY=secret,
        )


def test_production_public_registration_defaults_to_disabled() -> None:
    settings = Settings(
        _env_file=None,
        DATABASE_URL="postgresql://agenthq:agenthq@localhost:5432/agenthq",
        environment="production",
        JWT_SECRET_KEY="A-strong-production-secret-with-32-characters!",
    )

    assert settings.public_registration_enabled is False


def test_development_public_registration_defaults_to_enabled() -> None:
    settings = Settings(
        _env_file=None,
        DATABASE_URL="postgresql://agenthq:agenthq@localhost:5432/agenthq",
        environment="development",
    )

    assert settings.public_registration_enabled is True


def test_private_mcp_url_default_depends_on_environment() -> None:
    development = Settings(
        _env_file=None,
        DATABASE_URL="postgresql://agenthq:agenthq@localhost:5432/agenthq",
        environment="development",
    )
    production = Settings(
        _env_file=None,
        DATABASE_URL="postgresql://agenthq:agenthq@localhost:5432/agenthq",
        environment="production",
        JWT_SECRET_KEY="A-strong-production-secret-with-32-characters!",
    )

    assert development.private_mcp_urls_allowed is True
    assert production.private_mcp_urls_allowed is False


def test_smtp_email_backend_requires_host() -> None:
    with pytest.raises(ValidationError, match="SMTP_HOST is required"):
        Settings(
            _env_file=None,
            DATABASE_URL="postgresql://agenthq:agenthq@localhost:5432/agenthq",
            EMAIL_BACKEND="smtp",
        )


def test_production_startup_rejects_default_jwt_secret(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(
        "DATABASE_URL",
        "postgresql://agenthq:agenthq@localhost:5432/agenthq",
    )
    monkeypatch.setenv("ENVIRONMENT", "production")
    monkeypatch.setenv("JWT_SECRET_KEY", DEFAULT_JWT_SECRET_KEY)
    get_settings.cache_clear()

    with pytest.raises(ValidationError, match="Production requires a strong JWT_SECRET_KEY"):
        with TestClient(create_app()):
            pass

    get_settings.cache_clear()


def smtp_production_settings(frontend_url: str) -> Settings:
    return Settings(
        _env_file=None,
        DATABASE_URL="postgresql://agenthq:agenthq@localhost:5432/agenthq",
        environment="production",
        JWT_SECRET_KEY="A-strong-production-secret-with-32-characters!",
        EMAIL_BACKEND="smtp",
        SMTP_HOST="smtp.example.com",
        FRONTEND_BASE_URL=frontend_url,
    )


@pytest.mark.parametrize(
    "frontend_url",
    ["http://localhost:5173", "http://agenthq.example.com", "https://localhost"],
)
def test_production_smtp_requires_public_https_frontend(frontend_url: str) -> None:
    with pytest.raises(ValidationError, match="FRONTEND_BASE_URL"):
        smtp_production_settings(frontend_url)


def test_production_smtp_accepts_public_https_frontend() -> None:
    settings = smtp_production_settings("https://agenthq.example.com/")

    assert settings.normalized_frontend_base_url == "https://agenthq.example.com"


def test_smtp_ssl_and_starttls_are_mutually_exclusive() -> None:
    with pytest.raises(ValidationError, match="SMTP_USE_SSL"):
        Settings(
            _env_file=None,
            DATABASE_URL="postgresql://agenthq:agenthq@localhost:5432/agenthq",
            EMAIL_BACKEND="smtp",
            SMTP_HOST="smtp.example.com",
            SMTP_USE_SSL=True,
            SMTP_USE_TLS=True,
        )
