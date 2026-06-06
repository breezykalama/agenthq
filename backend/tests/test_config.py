import pytest

from app.core.config import get_cors_origins, normalize_database_url


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
