import logging

import pytest
from fastapi.testclient import TestClient

from app.core.config import get_settings
from app.core.rate_limit import rate_limiter

STRONG_JWT_SECRET = "A-strong-production-secret-with-32-characters!"
BOOTSTRAP_SECRET = "A-separate-bootstrap-secret-for-production!"


def configure_production(
    monkeypatch: pytest.MonkeyPatch,
    *,
    bootstrap_secret: str | None = BOOTSTRAP_SECRET,
    allow_public_registration: bool | None = None,
) -> None:
    monkeypatch.setenv("ENVIRONMENT", "production")
    monkeypatch.setenv("JWT_SECRET_KEY", STRONG_JWT_SECRET)
    monkeypatch.setenv("RATE_LIMITS_ENABLED", "false")
    if bootstrap_secret is None:
        monkeypatch.delenv("BOOTSTRAP_SECRET", raising=False)
    else:
        monkeypatch.setenv("BOOTSTRAP_SECRET", bootstrap_secret)
    if allow_public_registration is None:
        monkeypatch.delenv("ALLOW_PUBLIC_REGISTRATION", raising=False)
    else:
        monkeypatch.setenv(
            "ALLOW_PUBLIC_REGISTRATION",
            str(allow_public_registration).lower(),
        )
    get_settings.cache_clear()
    rate_limiter.clear()


def bootstrap_payload() -> dict[str, str]:
    return {
        "organization_name": "Secure Organization",
        "admin_full_name": "Secure Admin",
        "admin_email": "secure-admin@example.com",
        "admin_password": "StrongPassword123!",
    }


def test_production_bootstrap_requires_secret(
    unauthenticated_client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    configure_production(monkeypatch)

    response = unauthenticated_client.post(
        "/api/v1/organizations/bootstrap",
        json=bootstrap_payload(),
    )

    assert response.status_code == 403
    assert response.json()["detail"] == "Bootstrap authorization failed."


def test_production_bootstrap_rejects_invalid_secret_without_logging_it(
    unauthenticated_client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    configure_production(monkeypatch)
    invalid_secret = "do-not-log-this-bootstrap-secret"

    with caplog.at_level(logging.WARNING, logger="agenthq.security"):
        response = unauthenticated_client.post(
            "/api/v1/organizations/bootstrap",
            headers={"X-Bootstrap-Secret": invalid_secret},
            json=bootstrap_payload(),
        )

    assert response.status_code == 403
    assert "security_bootstrap_blocked" in caplog.text
    assert invalid_secret not in caplog.text
    assert BOOTSTRAP_SECRET not in caplog.text


def test_production_bootstrap_accepts_valid_secret(
    unauthenticated_client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    configure_production(monkeypatch)

    response = unauthenticated_client.post(
        "/api/v1/organizations/bootstrap",
        headers={"X-Bootstrap-Secret": BOOTSTRAP_SECRET},
        json=bootstrap_payload(),
    )

    assert response.status_code == 201


def test_existing_organization_bootstrap_still_returns_conflict(
    unauthenticated_client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    first = unauthenticated_client.post(
        "/api/v1/organizations/bootstrap",
        json=bootstrap_payload(),
    )
    configure_production(monkeypatch)

    response = unauthenticated_client.post(
        "/api/v1/organizations/bootstrap",
        json={
            **bootstrap_payload(),
            "organization_name": "Second Organization",
            "admin_email": "second-admin@example.com",
        },
    )

    assert first.status_code == 201
    assert response.status_code == 409


def test_public_registration_disabled_in_production_by_default(
    unauthenticated_client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    configure_production(monkeypatch)

    with caplog.at_level(logging.WARNING, logger="agenthq.security"):
        response = unauthenticated_client.post(
            "/api/v1/auth/register",
            json={
                "email": "blocked@example.com",
                "full_name": "Blocked User",
                "password": "StrongPassword123!",
            },
        )

    assert response.status_code == 403
    assert response.json()["detail"].startswith("Public registration is disabled.")
    assert "security_public_registration_blocked" in caplog.text
    assert "StrongPassword123!" not in caplog.text


def test_local_registration_remains_enabled(unauthenticated_client: TestClient) -> None:
    response = unauthenticated_client.post(
        "/api/v1/auth/register",
        json={
            "email": "local-user@example.com",
            "full_name": "Local User",
            "password": "StrongPassword123!",
        },
    )

    assert response.status_code == 201


def test_login_rate_limit_returns_429_and_logs_safely(
    unauthenticated_client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    monkeypatch.setenv("AUTH_RATE_LIMIT_ATTEMPTS", "2")
    get_settings.cache_clear()
    rate_limiter.clear()
    payload = {"email": "unknown@example.com", "password": "NeverLogThisPassword!"}

    with caplog.at_level(logging.WARNING, logger="agenthq.security"):
        first = unauthenticated_client.post("/api/v1/auth/login", json=payload)
        second = unauthenticated_client.post("/api/v1/auth/login", json=payload)
        limited = unauthenticated_client.post("/api/v1/auth/login", json=payload)

    assert first.status_code == 401
    assert second.status_code == 401
    assert limited.status_code == 429
    assert limited.json()["detail"] == "Too many requests. Please try again later."
    assert "security_login_failed" in caplog.text
    assert "security_rate_limit_exceeded" in caplog.text
    assert payload["email"] not in caplog.text
    assert payload["password"] not in caplog.text


def test_invite_accept_rate_limit_returns_429_without_logging_token(
    unauthenticated_client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    monkeypatch.setenv("AUTH_RATE_LIMIT_ATTEMPTS", "2")
    get_settings.cache_clear()
    rate_limiter.clear()
    invite_token = "never-log-this-invite-token"
    payload = {"token": invite_token, "password": "NeverLogThisPassword!"}

    with caplog.at_level(logging.WARNING, logger="agenthq.security"):
        first = unauthenticated_client.post("/api/v1/organization-invites/accept", json=payload)
        second = unauthenticated_client.post("/api/v1/organization-invites/accept", json=payload)
        limited = unauthenticated_client.post(
            "/api/v1/organization-invites/accept",
            json=payload,
        )

    assert first.status_code == 400
    assert second.status_code == 400
    assert limited.status_code == 429
    assert invite_token not in caplog.text
    assert payload["password"] not in caplog.text
