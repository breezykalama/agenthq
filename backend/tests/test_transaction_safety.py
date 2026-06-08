from typing import Any, cast

import pytest
from fastapi.testclient import TestClient

from app.models.audit_log import AuditAction
from app.schemas.audit_log import AuditLogCreate
from app.services import audit_logs as audit_log_service


def create_agent(client: TestClient, name: str) -> dict[str, Any]:
    response = client.post(
        "/api/v1/agents",
        json={
            "name": name,
            "owner": "platform-team",
            "department": "governance",
            "risk_level": "low",
        },
    )
    assert response.status_code == 201
    return cast(dict[str, Any], response.json())


def fail_specific_audit(
    monkeypatch: pytest.MonkeyPatch,
    action: AuditAction,
) -> None:
    original = audit_log_service.create_critical_audit_log

    def create_or_fail(db: object, audit_create: AuditLogCreate) -> object:
        if audit_create.action == action:
            raise audit_log_service.AuditLoggingError("Critical action could not be audited.")
        return original(db, audit_create)  # type: ignore[arg-type]

    monkeypatch.setattr(audit_log_service, "create_critical_audit_log", create_or_fail)


def audit_total(client: TestClient, action: AuditAction) -> int:
    response = client.get("/api/v1/audit-logs", params={"action": action.value})
    assert response.status_code == 200
    return cast(int, response.json()["total"])


def test_execution_audit_failure_rolls_back_execution_and_policy_audit(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    agent = create_agent(client, "Atomic Execution Agent")
    fail_specific_audit(monkeypatch, AuditAction.EXECUTION_CREATED)

    response = client.post(
        "/api/v1/executions",
        json={
            "agent_id": agent["id"],
            "action_name": "atomic_action",
            "risk_level": "low",
        },
    )

    assert response.status_code == 503
    assert client.get("/api/v1/executions").json()["total"] == 0
    assert audit_total(client, AuditAction.EXECUTION_CREATED) == 0
    assert audit_total(client, AuditAction.POLICY_DECISION_EVALUATED) == 0


def test_mcp_sync_audit_failure_rolls_back_linked_agent_tools_and_server_state(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    server = client.post(
        "/api/v1/mcp-servers",
        json={"name": "Atomic MCP Server", "server_url": "https://mcp.example.com/server"},
    ).json()
    fail_specific_audit(monkeypatch, AuditAction.MCP_SERVER_SYNCED)

    response = client.post(f"/api/v1/mcp-servers/{server['id']}/sync")

    assert response.status_code == 503
    persisted_server = client.get(f"/api/v1/mcp-servers/{server['id']}").json()
    assert persisted_server["status"] == "disconnected"
    assert persisted_server["agent_id"] is None
    assert persisted_server["last_sync_at"] is None
    assert client.get("/api/v1/agents").json()["total"] == 0
    assert audit_total(client, AuditAction.MCP_SERVER_SYNCED) == 0
    assert audit_total(client, AuditAction.AGENT_CREATED) == 0


def test_user_deactivation_audit_failure_rolls_back_user_state(
    client: TestClient,
    unauthenticated_client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    registration = unauthenticated_client.post(
        "/api/v1/auth/register",
        json={
            "email": "atomic-user@agenthq.example",
            "full_name": "Atomic User",
            "password": "AtomicPassword123!",
        },
    )
    assert registration.status_code == 201
    user = registration.json()
    fail_specific_audit(monkeypatch, AuditAction.USER_DEACTIVATED)

    response = client.post(f"/api/v1/users/{user['id']}/deactivate")

    assert response.status_code == 503
    assert client.get(f"/api/v1/users/{user['id']}").json()["is_active"] is True
    assert audit_total(client, AuditAction.USER_DEACTIVATED) == 0


def test_direct_policy_decision_audit_failure_leaves_no_audit(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    agent = create_agent(client, "Atomic Policy Agent")
    fail_specific_audit(monkeypatch, AuditAction.POLICY_DECISION_EVALUATED)

    response = client.post(
        "/api/v1/policy-decisions/evaluate",
        json={
            "agent_id": agent["id"],
            "requested_action": "atomic_policy_action",
            "risk_level": "low",
        },
    )

    assert response.status_code == 503
    assert audit_total(client, AuditAction.POLICY_DECISION_EVALUATED) == 0
