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
