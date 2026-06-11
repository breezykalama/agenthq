from typing import Any, cast
from uuid import uuid4

import pytest
from fastapi import Request
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.core import rate_limit as rate_limit_module
from app.core.config import get_settings
from app.core.rate_limit import RateLimitDecision, reset_rate_limit_backend
from app.models.audit_log import AuditAction


def configure_limit(
    monkeypatch: pytest.MonkeyPatch,
    *,
    setting: str,
    attempts: int,
) -> None:
    monkeypatch.setenv("RATE_LIMITS_ENABLED", "true")
    monkeypatch.setenv(setting, str(attempts))
    get_settings.cache_clear()
    reset_rate_limit_backend()


def execution_payload(agent_id: str) -> dict[str, object]:
    return {
        "agent_id": agent_id,
        "action_name": "summarize_policy",
        "risk_level": "low",
        "status": "succeeded",
    }


def test_login_rate_limit_includes_retry_after(
    unauthenticated_client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    configure_limit(monkeypatch, setting="AUTH_RATE_LIMIT_ATTEMPTS", attempts=1)
    payload = {"email": "rate-limited@example.com", "password": "StrongPassword123!"}

    first = unauthenticated_client.post("/api/v1/auth/login", json=payload)
    limited = unauthenticated_client.post("/api/v1/auth/login", json=payload)

    assert first.status_code == 401
    assert limited.status_code == 429
    assert limited.headers["Retry-After"] == "60"
    assert limited.json() == {"detail": "Too many requests. Please try again later."}


def test_login_uses_ip_and_hashed_identifier_keys(monkeypatch: pytest.MonkeyPatch) -> None:
    class RecordingBackend:
        def __init__(self) -> None:
            self.keys: list[str] = []

        def check(self, key: str, *, limit: int, window_seconds: int) -> RateLimitDecision:
            self.keys.append(key)
            return RateLimitDecision(allowed=True, retry_after=0)

    backend = RecordingBackend()
    monkeypatch.setattr(rate_limit_module, "get_rate_limit_backend", lambda: backend)
    request = Request(
        {
            "type": "http",
            "method": "POST",
            "path": "/api/v1/auth/login",
            "headers": [],
            "query_string": b"",
            "client": ("192.0.2.10", 5000),
            "server": ("testserver", 80),
            "scheme": "http",
        }
    )

    rate_limit_module.enforce_auth_rate_limit(
        request,
        "login",
        identifier="private@example.com",
    )

    assert backend.keys[0] == "auth:login:ip:192.0.2.10"
    assert backend.keys[1].startswith("auth:login:identifier:")
    assert "private@example.com" not in backend.keys[1]


def test_authenticated_execution_limit_creates_security_audit_event(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    agent = client.post(
        "/api/v1/agents",
        json={
            "name": "Rate Limited Agent",
            "owner": "platform-team",
            "department": "governance",
            "risk_level": "low",
        },
    ).json()
    configure_limit(monkeypatch, setting="EXECUTION_RATE_LIMIT_ATTEMPTS", attempts=1)

    first = client.post("/api/v1/executions", json=execution_payload(agent["id"]))
    limited = client.post("/api/v1/executions", json=execution_payload(agent["id"]))
    audit_response = client.get(
        "/api/v1/audit-logs",
        params={"action": AuditAction.SECURITY_RATE_LIMITED.value},
    )

    assert first.status_code == 201
    assert limited.status_code == 429
    assert limited.headers["Retry-After"] == "60"
    audit_logs = cast(list[dict[str, Any]], audit_response.json()["items"])
    assert len(audit_logs) == 1
    assert audit_logs[0]["outcome"] == "denied"
    assert audit_logs[0]["reason"] == "rate_limit_exceeded"
    assert audit_logs[0]["metadata"] == {
        "endpoint": "/api/v1/executions",
        "scope": "execution_create",
    }


def test_authenticated_rate_limit_keys_are_isolated_between_organizations(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class RecordingBackend:
        def __init__(self) -> None:
            self.keys: list[str] = []

        def check(self, key: str, *, limit: int, window_seconds: int) -> RateLimitDecision:
            self.keys.append(key)
            return RateLimitDecision(allowed=True, retry_after=0)

    backend = RecordingBackend()
    monkeypatch.setattr(rate_limit_module, "get_rate_limit_backend", lambda: backend)
    request = Request(
        {
            "type": "http",
            "method": "POST",
            "path": "/api/v1/executions",
            "headers": [],
            "query_string": b"",
            "client": ("127.0.0.1", 5000),
            "server": ("testserver", 80),
            "scheme": "http",
        }
    )
    actor_id = uuid4()
    with Session() as db:
        db.info["audit_actor_user_id"] = actor_id
        db.info["organization_id"] = uuid4()
        rate_limit_module.enforce_authenticated_rate_limit(
            request,
            db,
            "execution_create",
            resource_type="execution",
        )
        db.info["organization_id"] = uuid4()
        rate_limit_module.enforce_authenticated_rate_limit(
            request,
            db,
            "execution_create",
            resource_type="execution",
        )

    assert len(backend.keys) == 2
    assert backend.keys[0] != backend.keys[1]


def test_rate_limits_can_be_disabled_for_local_tests(
    unauthenticated_client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("RATE_LIMITS_ENABLED", "false")
    monkeypatch.setenv("AUTH_RATE_LIMIT_ATTEMPTS", "1")
    get_settings.cache_clear()
    reset_rate_limit_backend()
    payload = {"email": "not-limited@example.com", "password": "StrongPassword123!"}

    responses = [
        unauthenticated_client.post("/api/v1/auth/login", json=payload) for _ in range(3)
    ]

    assert [response.status_code for response in responses] == [401, 401, 401]


def test_production_without_redis_fails_closed(
    unauthenticated_client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ENVIRONMENT", "production")
    monkeypatch.setenv("JWT_SECRET_KEY", "A-strong-production-secret-with-32-characters!")
    monkeypatch.setenv("RATE_LIMITS_ENABLED", "true")
    monkeypatch.delenv("REDIS_URL", raising=False)
    get_settings.cache_clear()
    reset_rate_limit_backend()

    response = unauthenticated_client.post(
        "/api/v1/auth/login",
        json={"email": "secure@example.com", "password": "StrongPassword123!"},
    )

    assert response.status_code == 503
    assert response.json() == {"detail": "Abuse protection is temporarily unavailable."}
