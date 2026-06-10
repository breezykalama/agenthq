from typing import Any, cast
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import StaticPool, create_engine, select
from sqlalchemy.orm import Session

from app.core.audit_redaction import REDACTED, redact_audit_snapshot
from app.db.base import Base
from app.models.audit_log import AuditAction, AuditLog, AuditOutcome, JsonObject
from app.repositories import audit_logs as audit_log_repository
from app.schemas.audit_log import AuditLogCreate

JsonResponse = dict[str, Any]


def agent_payload(name: str = "Policy Review Agent") -> dict[str, str]:
    return {
        "name": name,
        "description": "Reviews internal policy drafts.",
        "owner": "platform-team",
        "department": "governance",
        "risk_level": "medium",
        "status": "draft",
    }


def create_agent(client: TestClient, name: str = "Policy Review Agent") -> JsonResponse:
    response = client.post("/api/v1/agents", json=agent_payload(name=name))
    assert response.status_code == 201
    return cast(JsonResponse, response.json())


def audit_logs(client: TestClient, query: dict[str, str] | None = None) -> list[JsonResponse]:
    response = client.get("/api/v1/audit-logs", params=query or {})
    assert response.status_code == 200
    data = cast(JsonResponse, response.json())
    return cast(list[JsonResponse], data["items"])


def test_audit_log_created_after_agent_create(client: TestClient) -> None:
    created_agent = create_agent(client)

    logs = audit_logs(client)

    assert len(logs) == 1
    log = logs[0]
    assert log["actor"] == "system"
    assert log["action"] == "agent.created"
    assert log["entity_type"] == "agent"
    assert log["entity_id"] == created_agent["id"]
    assert log["before"] is None
    assert log["after"]["id"] == created_agent["id"]
    assert log["after"]["name"] == "Policy Review Agent"


def test_audit_log_created_after_agent_update(client: TestClient) -> None:
    created_agent = create_agent(client)

    response = client.patch(
        f"/api/v1/agents/{created_agent['id']}",
        json={"name": "Policy Approval Agent", "status": "active"},
    )
    assert response.status_code == 200

    logs = audit_logs(client, {"action": "agent.updated"})

    assert len(logs) == 1
    log = logs[0]
    assert log["before"]["name"] == "Policy Review Agent"
    assert log["before"]["status"] == "draft"
    assert log["after"]["name"] == "Policy Approval Agent"
    assert log["after"]["status"] == "active"


def test_audit_log_created_after_agent_soft_delete(client: TestClient) -> None:
    created_agent = create_agent(client)

    response = client.delete(f"/api/v1/agents/{created_agent['id']}")
    assert response.status_code == 204

    logs = audit_logs(client, {"action": "agent.deleted"})

    assert len(logs) == 1
    log = logs[0]
    assert log["before"]["deleted_at"] is None
    assert log["after"]["deleted_at"] is not None
    assert log["entity_id"] == created_agent["id"]


def test_before_after_snapshots_are_correct(client: TestClient) -> None:
    created_agent = create_agent(client)

    response = client.patch(
        f"/api/v1/agents/{created_agent['id']}",
        json={"description": "Updated description.", "risk_level": "high"},
    )
    assert response.status_code == 200

    logs = audit_logs(client, {"action": "agent.updated"})
    log = logs[0]

    assert log["before"]["description"] == "Reviews internal policy drafts."
    assert log["before"]["risk_level"] == "medium"
    assert log["after"]["description"] == "Updated description."
    assert log["after"]["risk_level"] == "high"
    assert log["before"]["id"] == log["after"]["id"] == created_agent["id"]


def test_list_audit_logs(client: TestClient) -> None:
    created_agent = create_agent(client)
    client.patch(f"/api/v1/agents/{created_agent['id']}", json={"status": "active"})
    client.delete(f"/api/v1/agents/{created_agent['id']}")

    response = client.get("/api/v1/audit-logs")

    assert response.status_code == 200
    data = response.json()
    assert data["total"] == 3
    assert {log["action"] for log in data["items"]} == {
        "agent.created",
        "agent.updated",
        "agent.deleted",
    }


def test_filter_audit_logs_by_entity_type(client: TestClient) -> None:
    create_agent(client)

    logs = audit_logs(client, {"entity_type": "agent"})

    assert len(logs) == 1
    assert logs[0]["entity_type"] == "agent"


def test_filter_audit_logs_by_entity_id(client: TestClient) -> None:
    first_agent = create_agent(client, "Policy Review Agent")
    create_agent(client, "Procurement Triage Agent")

    logs = audit_logs(client, {"entity_id": str(first_agent["id"])})

    assert len(logs) == 1
    assert logs[0]["entity_id"] == first_agent["id"]


def test_filter_audit_logs_by_action(client: TestClient) -> None:
    created_agent = create_agent(client)
    client.patch(f"/api/v1/agents/{created_agent['id']}", json={"status": "active"})

    logs = audit_logs(client, {"action": "agent.updated"})

    assert len(logs) == 1
    assert logs[0]["action"] == "agent.updated"


def test_audit_redaction_redacts_top_level_and_nested_secrets() -> None:
    snapshot: JsonObject = {
        "name": "Safe Agent",
        "password_hash": "argon-secret",
        "TOKEN_HASH": "invite-secret",
        "nested": {
            "api_key": "provider-secret",
            "Authorization": "Bearer sensitive-token",
            "safe_status": "connected",
        },
        "items": [{"bootstrap-secret": "bootstrap-value"}, {"risk_level": "high"}],
        "invite_url": "/accept-invite?token=raw-invite-token",
    }

    redacted = redact_audit_snapshot(snapshot)

    assert redacted is not None
    assert redacted["name"] == "Safe Agent"
    assert redacted["password_hash"] == REDACTED
    assert redacted["TOKEN_HASH"] == REDACTED
    assert redacted["nested"]["api_key"] == REDACTED  # type: ignore[index]
    assert redacted["nested"]["Authorization"] == REDACTED  # type: ignore[index]
    assert redacted["nested"]["safe_status"] == "connected"  # type: ignore[index]
    assert redacted["items"][0]["bootstrap-secret"] == REDACTED  # type: ignore[index]
    assert redacted["items"][1]["risk_level"] == "high"  # type: ignore[index]
    assert redacted["invite_url"] == REDACTED


def test_audit_repository_redacts_snapshots_before_storage() -> None:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        audit_log = audit_log_repository.create_audit_log(
            db,
            AuditLogCreate(
                action=AuditAction.AGENT_UPDATED,
                entity_type="agent",
                entity_id=uuid4(),
                before={"password_hash": "secret", "name": "Safe Agent"},
                after={
                    "nested": {"token_hash": "secret"},
                    "endpoint": "https://user:password@example.com/mcp",
                    "status": "active",
                },
            ),
        )

        assert audit_log.before == {"password_hash": REDACTED, "name": "Safe Agent"}
        assert audit_log.after == {
            "nested": {"token_hash": REDACTED},
            "endpoint": REDACTED,
            "status": "active",
        }
    engine.dispose()


def test_audit_event_contains_standard_request_and_actor_context(client: TestClient) -> None:
    response = client.post(
        "/api/v1/agents",
        headers={"X-Request-ID": "audit-request-123", "User-Agent": "AgentHQ Audit Test"},
        json=agent_payload(),
    )

    assert response.status_code == 201
    log = audit_logs(client, {"action": "agent.created"})[0]
    assert log["event_id"] == log["id"]
    assert log["timestamp"] == log["created_at"]
    assert log["resource_type"] == log["entity_type"] == "agent"
    assert log["resource_id"] == log["entity_id"] == response.json()["id"]
    assert log["actor_user_id"] is not None
    assert log["actor_role"] == "admin"
    assert log["outcome"] == "success"
    assert log["request_id"] == "audit-request-123"
    assert log["user_agent"] == "AgentHQ Audit Test"
    assert log["ip_address"] == "testclient"


def test_denied_permission_creates_security_event(
    client: TestClient,
    unauthenticated_client: TestClient,
) -> None:
    registration = unauthenticated_client.post(
        "/api/v1/auth/register",
        json={
            "email": "denied-owner@example.com",
            "full_name": "Denied Owner",
            "password": "StrongPassword123!",
        },
    )
    token = unauthenticated_client.post(
        "/api/v1/auth/login",
        json={"email": "denied-owner@example.com", "password": "StrongPassword123!"},
    ).json()["access_token"]

    denied = unauthenticated_client.get(
        "/api/v1/mcp-servers",
        headers={
            "Authorization": f"Bearer {token}",
            "X-Request-ID": "denied-request-123",
        },
    )

    assert registration.status_code == 201
    assert denied.status_code == 403
    log = audit_logs(client, {"action": "security.access_denied"})[0]
    assert log["actor_user_id"] == registration.json()["id"]
    assert log["actor_role"] == "agent_owner"
    assert log["outcome"] == "denied"
    assert log["request_id"] == "denied-request-123"
    assert log["metadata"]["attempted_action"] == "manage_mcp_servers"


def test_failed_login_creates_redacted_failed_event(
    client: TestClient,
    unauthenticated_client: TestClient,
) -> None:
    registration = unauthenticated_client.post(
        "/api/v1/auth/register",
        json={
            "email": "failed-login@example.com",
            "full_name": "Failed Login",
            "password": "StrongPassword123!",
        },
    )
    failed = unauthenticated_client.post(
        "/api/v1/auth/login",
        json={"email": "failed-login@example.com", "password": "NeverStoreThisPassword!"},
    )

    assert registration.status_code == 201
    assert failed.status_code == 401
    log = audit_logs(client, {"action": "auth.login_failed"})[0]
    assert log["outcome"] == "failed"
    assert log["actor_user_id"] == registration.json()["id"]
    assert "failed-login@example.com" not in str(log)
    assert "NeverStoreThisPassword!" not in str(log)


def test_audit_log_api_is_append_only(client: TestClient) -> None:
    create_agent(client)
    audit_log_id = audit_logs(client)[0]["id"]

    update = client.patch(f"/api/v1/audit-logs/{audit_log_id}", json={"reason": "tamper"})
    delete = client.delete(f"/api/v1/audit-logs/{audit_log_id}")

    assert update.status_code in {404, 405}
    assert delete.status_code in {404, 405}


def test_audit_model_rejects_update_and_delete() -> None:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        audit_log = audit_log_repository.create_audit_log(
            db,
            AuditLogCreate(
                action=AuditAction.SECURITY_ACCESS_DENIED,
                entity_type="api",
                entity_id=uuid4(),
                outcome=AuditOutcome.DENIED,
            ),
        )
        audit_log.reason = "tamper"
        with pytest.raises(ValueError, match="append-only"):
            db.commit()
        db.rollback()
        persisted = db.scalar(select(AuditLog).where(AuditLog.id == audit_log.id))
        assert persisted is not None
    engine.dispose()


def test_audit_metadata_is_redacted_before_storage() -> None:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        audit_log = audit_log_repository.create_audit_log(
            db,
            AuditLogCreate(
                action=AuditAction.SECURITY_ACCESS_DENIED,
                entity_type="api",
                entity_id=uuid4(),
                metadata={
                    "token": "raw-token",
                    "nested": {"password": "raw-password"},
                    "safe": "visible",
                },
            ),
        )

        assert audit_log.event_metadata == {
            "token": REDACTED,
            "nested": {"password": REDACTED},
            "safe": "visible",
        }
    engine.dispose()
