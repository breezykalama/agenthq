from typing import Any, cast

import pytest
from fastapi.testclient import TestClient

from app.services import audit_logs as audit_log_service
from app.services import executions as execution_service

JsonResponse = dict[str, Any]


def create_agent(client: TestClient, name: str = "Policy Review Agent") -> JsonResponse:
    response = client.post(
        "/api/v1/agents",
        json={
            "name": name,
            "description": "Reviews internal policy drafts.",
            "owner": "platform-team",
            "department": "governance",
            "risk_level": "medium",
            "status": "draft",
        },
    )
    assert response.status_code == 201
    return cast(JsonResponse, response.json())


def create_tool(
    client: TestClient,
    agent_id: str,
    name: str = "document_search",
    is_enabled: bool = True,
) -> JsonResponse:
    response = client.post(
        f"/api/v1/agents/{agent_id}/tools",
        json={
            "name": name,
            "description": "Search internal policy documents.",
            "permission": "read",
            "risk_level": "low",
            "is_enabled": is_enabled,
        },
    )
    assert response.status_code == 201
    return cast(JsonResponse, response.json())


def create_approval(client: TestClient, agent_id: str) -> JsonResponse:
    response = client.post(
        "/api/v1/approvals",
        json={
            "agent_id": agent_id,
            "requested_action": "run_high_risk_action",
            "requested_by": "platform-team",
            "risk_level": "high",
        },
    )
    assert response.status_code == 201
    return cast(JsonResponse, response.json())


def approve_approval(client: TestClient, approval_id: str) -> JsonResponse:
    response = client.post(
        f"/api/v1/approvals/{approval_id}/approve",
        json={"approver": "risk-office"},
    )
    assert response.status_code == 200
    return cast(JsonResponse, response.json())


def create_policy_rule(
    client: TestClient,
    name: str,
    effect: str,
    risk_level: str = "low",
    scope: str = "global",
    agent_id: str | None = None,
    tool_id: str | None = None,
    priority: int = 100,
) -> JsonResponse:
    payload: dict[str, object] = {
        "name": name,
        "description": "Execution enforcement policy.",
        "scope": scope,
        "risk_level": risk_level,
        "effect": effect,
        "is_enabled": True,
        "priority": priority,
    }
    if agent_id is not None:
        payload["agent_id"] = agent_id
    if tool_id is not None:
        payload["tool_id"] = tool_id

    response = client.post("/api/v1/policy-rules", json=payload)
    assert response.status_code == 201
    return cast(JsonResponse, response.json())


def execution_payload(
    agent_id: str,
    risk_level: str = "low",
    status: str = "succeeded",
    tool_id: str | None = None,
    approval_id: str | None = None,
) -> dict[str, object]:
    payload: dict[str, object] = {
        "agent_id": agent_id,
        "action_name": "summarize_policy",
        "risk_level": risk_level,
        "status": status,
    }
    if tool_id is not None:
        payload["tool_id"] = tool_id
    if approval_id is not None:
        payload["approval_id"] = approval_id
    return payload


def create_execution(
    client: TestClient,
    agent_id: str,
    risk_level: str = "low",
    status: str = "succeeded",
    tool_id: str | None = None,
    approval_id: str | None = None,
) -> JsonResponse:
    response = client.post(
        "/api/v1/executions",
        json=execution_payload(
            agent_id,
            risk_level=risk_level,
            status=status,
            tool_id=tool_id,
            approval_id=approval_id,
        ),
    )
    assert response.status_code == 201
    return cast(JsonResponse, response.json())


def audit_logs(client: TestClient, action: str) -> list[JsonResponse]:
    response = client.get("/api/v1/audit-logs", params={"action": action})
    assert response.status_code == 200
    data = cast(JsonResponse, response.json())
    return cast(list[JsonResponse], data["items"])


def test_low_risk_execution_defaults_to_allowed_by_policy(client: TestClient) -> None:
    agent = create_agent(client)

    execution = create_execution(client, str(agent["id"]), risk_level="low")

    assert execution["status"] == "succeeded"
    assert execution["policy_decision"] == "allow"
    assert execution["policy_rule_id"] is None
    assert execution["policy_decision_reason"]


def test_high_risk_execution_defaults_to_requires_approval_by_policy(client: TestClient) -> None:
    agent = create_agent(client)

    execution = create_execution(client, str(agent["id"]), risk_level="high")

    assert execution["status"] == "requires_approval"
    assert execution["policy_decision"] == "require_approval"


def test_blocked_policy_creates_blocked_execution(client: TestClient) -> None:
    agent = create_agent(client)
    create_policy_rule(client, "Block all", "block")

    execution = create_execution(client, str(agent["id"]), risk_level="low")

    assert execution["status"] == "blocked"
    assert execution["policy_decision"] == "block"


def test_blocked_execution_has_completed_at(client: TestClient) -> None:
    agent = create_agent(client)
    create_policy_rule(client, "Block all", "block")

    execution = create_execution(client, str(agent["id"]), risk_level="low")

    assert execution["completed_at"] is not None


def test_allow_policy_permits_high_risk_execution_without_approval(client: TestClient) -> None:
    agent = create_agent(client)
    create_policy_rule(client, "Allow high risk", "allow", risk_level="high")

    execution = create_execution(client, str(agent["id"]), risk_level="high")

    assert execution["status"] == "succeeded"
    assert execution["policy_decision"] == "allow"


def test_require_approval_policy_requires_approved_approval(client: TestClient) -> None:
    agent = create_agent(client)
    create_policy_rule(client, "Approval required", "require_approval")

    execution = create_execution(client, str(agent["id"]), risk_level="low")

    assert execution["status"] == "requires_approval"
    assert execution["policy_decision"] == "require_approval"


def test_approved_approval_allows_require_approval_execution(client: TestClient) -> None:
    agent = create_agent(client)
    create_policy_rule(client, "Approval required", "require_approval")
    approval = approve_approval(client, str(create_approval(client, str(agent["id"]))["id"]))

    execution = create_execution(
        client,
        str(agent["id"]),
        risk_level="low",
        approval_id=str(approval["id"]),
    )

    assert execution["status"] == "succeeded"
    assert execution["approval_id"] == approval["id"]
    assert execution["policy_decision"] == "require_approval"


def test_execution_with_tool_id_validates_tool_belongs_to_agent(client: TestClient) -> None:
    first_agent = create_agent(client, "Policy Review Agent")
    second_agent = create_agent(client, "Procurement Triage Agent")
    tool = create_tool(client, str(first_agent["id"]))

    response = client.post(
        "/api/v1/executions",
        json=execution_payload(str(second_agent["id"]), tool_id=str(tool["id"])),
    )

    assert response.status_code == 404


def test_disabled_tool_rejected(client: TestClient) -> None:
    agent = create_agent(client)
    tool = create_tool(client, str(agent["id"]), is_enabled=False)

    response = client.post(
        "/api/v1/executions",
        json=execution_payload(str(agent["id"]), tool_id=str(tool["id"])),
    )

    assert response.status_code == 409


def test_execution_stores_matched_policy_rule_id(client: TestClient) -> None:
    agent = create_agent(client)
    rule = create_policy_rule(client, "Block all", "block")

    execution = create_execution(client, str(agent["id"]))

    assert execution["policy_rule_id"] == rule["id"]


def test_execution_stores_policy_decision_reason(client: TestClient) -> None:
    agent = create_agent(client)
    create_policy_rule(client, "Block all", "block")

    execution = create_execution(client, str(agent["id"]))

    assert execution["policy_decision_reason"] == "Matched global-scoped policy rule."


def test_execution_create_creates_execution_and_policy_decision_audits(
    client: TestClient,
) -> None:
    agent = create_agent(client)

    execution = create_execution(client, str(agent["id"]), risk_level="high")
    execution_logs = audit_logs(client, "execution.created")
    decision_logs = audit_logs(client, "policy_decision.evaluated")

    assert len(execution_logs) == 1
    assert len(decision_logs) == 1
    assert execution_logs[0]["entity_id"] == execution["id"]
    assert execution_logs[0]["after"]["policy_decision"] == "require_approval"
    assert decision_logs[0]["after"]["request"]["requested_action"] == "summarize_policy"


def test_policy_decision_failure_fails_closed(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    agent = create_agent(client)

    def fail_policy_evaluation(*args: object, **kwargs: object) -> None:
        raise RuntimeError("Policy database unavailable")

    monkeypatch.setattr(
        execution_service.policy_decision_service,
        "evaluate_policy_decision",
        fail_policy_evaluation,
    )

    response = client.post(
        "/api/v1/executions",
        json=execution_payload(str(agent["id"]), risk_level="high"),
    )

    assert response.status_code == 201
    execution = response.json()
    assert execution["status"] == "blocked"
    assert execution["policy_decision"] == "block"
    assert "fail-closed fallback" in execution["policy_decision_reason"]
    decision_logs = audit_logs(client, "policy_decision.evaluated")
    assert decision_logs[-1]["after"]["response"]["decision"] == "block"


def test_execution_create_is_compensated_when_critical_audit_fails(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    agent = create_agent(client)

    def fail_audit(*args: object, **kwargs: object) -> None:
        raise audit_log_service.AuditLoggingError("Critical action could not be audited.")

    monkeypatch.setattr(audit_log_service, "create_critical_audit_log", fail_audit)

    response = client.post(
        "/api/v1/executions",
        json=execution_payload(str(agent["id"]), risk_level="low"),
    )

    assert response.status_code == 503
    assert response.json()["detail"] == "Critical action could not be audited."
    assert client.get("/api/v1/executions").json()["total"] == 0
