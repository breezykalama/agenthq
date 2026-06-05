from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from app.core.config import get_settings
from app.main import create_app


@pytest.fixture(autouse=True)
def database_url(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    monkeypatch.setenv(
        "DATABASE_URL",
        "postgresql+psycopg://agenthq:agenthq@localhost:5432/agenthq",
    )
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def test_health_check() -> None:
    with TestClient(create_app()) as client:
        response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
