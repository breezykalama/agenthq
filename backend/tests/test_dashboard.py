from decimal import Decimal
from typing import Any, cast

from fastapi.testclient import TestClient

JsonResponse = dict[str, Any]


def agent_payload(
    name: str,
    status: str = "draft",
    risk_level: str = "low",
) -> dict[str, str]:
    return {
        "name": name,
        "description": "Dashboard test agent.",
        "owner": "platform-team",
        "department": "governance",
        "risk_level": risk_level,
        "status": status,
    }


def create_agent(
    client: TestClient,
    name: str,
    status: str = "draft",
    risk_level: str = "low",
) -> JsonResponse:
    response = client.post(
        "/api/v1/agents",
        json=agent_payload(name, status=status, risk_level=risk_level),
    )
    assert response.status_code == 201
    return cast(JsonResponse, response.json())


def create_approval(client: TestClient, agent_id: str, risk_level: str = "high") -> JsonResponse:
    response = client.post(
        "/api/v1/approvals",
        json={
            "agent_id": agent_id,
            "requested_action": "activate_agent",
            "requested_by": "platform-team",
            "risk_level": risk_level,
        },
    )
    assert response.status_code == 201
    return cast(JsonResponse, response.json())


def create_execution(
    client: TestClient,
    agent_id: str,
    status: str = "succeeded",
    risk_level: str = "low",
    cost_usd: str | None = "1.50",
    latency_ms: int | None = 100,
) -> JsonResponse:
    payload: dict[str, object] = {
        "agent_id": agent_id,
        "action_name": "dashboard_action",
        "risk_level": risk_level,
        "status": status,
    }
    if cost_usd is not None:
        payload["cost_usd"] = cost_usd
    if latency_ms is not None:
        payload["latency_ms"] = latency_ms

    response = client.post("/api/v1/executions", json=payload)
    assert response.status_code == 201
    return cast(JsonResponse, response.json())


def get_summary(client: TestClient) -> JsonResponse:
    response = client.get("/api/v1/dashboard/summary")
    assert response.status_code == 200
    return cast(JsonResponse, response.json())


def test_empty_dashboard_returns_zeros(client: TestClient) -> None:
    summary = get_summary(client)

    assert summary == {
        "total_agents": 0,
        "active_agents": 0,
        "disabled_agents": 0,
        "archived_agents": 0,
        "total_executions": 0,
        "executions_today": 0,
        "succeeded_executions": 0,
        "failed_executions": 0,
        "blocked_executions": 0,
        "requires_approval_executions": 0,
        "pending_approvals": 0,
        "approved_approvals": 0,
        "rejected_approvals": 0,
        "open_incidents": 0,
        "investigating_incidents": 0,
        "resolved_incidents": 0,
        "critical_incidents": 0,
        "total_cost_usd": "0",
        "average_latency_ms": 0.0,
    }


def test_summary_counts_agents_correctly(client: TestClient) -> None:
    create_agent(client, "Draft Agent")
    create_agent(client, "Active Agent", status="active")
    create_agent(client, "Disabled Agent", status="disabled")
    create_agent(client, "Archived Agent", status="archived")

    summary = get_summary(client)

    assert summary["total_agents"] == 4
    assert summary["active_agents"] == 1
    assert summary["disabled_agents"] == 1
    assert summary["archived_agents"] == 1


def test_summary_counts_executions_correctly(client: TestClient) -> None:
    agent = create_agent(client, "Execution Agent")
    create_execution(client, str(agent["id"]), status="succeeded")
    create_execution(client, str(agent["id"]), status="failed")
    create_execution(client, str(agent["id"]), status="blocked")
    create_execution(client, str(agent["id"]), status="running", risk_level="high")

    summary = get_summary(client)

    assert summary["total_executions"] == 4
    assert summary["executions_today"] == 4
    assert summary["succeeded_executions"] == 1
    assert summary["failed_executions"] == 1
    assert summary["blocked_executions"] == 1
    assert summary["requires_approval_executions"] == 1


def test_summary_counts_approvals_correctly(client: TestClient) -> None:
    agent = create_agent(client, "Approval Agent")
    pending = create_approval(client, str(agent["id"]))
    approved = create_approval(client, str(agent["id"]))
    rejected = create_approval(client, str(agent["id"]))
    client.post(f"/api/v1/approvals/{approved['id']}/approve")
    client.post(f"/api/v1/approvals/{rejected['id']}/reject")

    summary = get_summary(client)

    assert pending["status"] == "pending"
    assert summary["pending_approvals"] == 1
    assert summary["approved_approvals"] == 1
    assert summary["rejected_approvals"] == 1


def test_summary_counts_incidents_correctly(client: TestClient) -> None:
    agent = create_agent(client, "Incident Agent")
    open_response = client.post(
        "/api/v1/incidents",
        json={
            "agent_id": agent["id"],
            "title": "Open incident",
            "description": "An open incident.",
            "severity": "critical",
        },
    )
    investigating_response = client.post(
        "/api/v1/incidents",
        json={
            "agent_id": agent["id"],
            "title": "Investigating incident",
            "description": "An investigating incident.",
            "severity": "high",
            "status": "investigating",
        },
    )
    resolved_response = client.post(
        "/api/v1/incidents",
        json={
            "agent_id": agent["id"],
            "title": "Resolved incident",
            "description": "A resolved incident.",
            "severity": "medium",
        },
    )
    assert open_response.status_code == 201
    assert investigating_response.status_code == 201
    assert resolved_response.status_code == 201
    client.post(
        f"/api/v1/incidents/{resolved_response.json()['id']}/resolve",
        json={"resolution_notes": "Resolved."},
    )

    summary = get_summary(client)

    assert summary["open_incidents"] == 1
    assert summary["investigating_incidents"] == 1
    assert summary["resolved_incidents"] == 1
    assert summary["critical_incidents"] == 1


def test_soft_deleted_agents_excluded_from_counts(client: TestClient) -> None:
    deleted_agent = create_agent(client, "Deleted Agent", status="active")
    create_agent(client, "Visible Agent", status="disabled")
    client.delete(f"/api/v1/agents/{deleted_agent['id']}")

    summary = get_summary(client)

    assert summary["total_agents"] == 1
    assert summary["active_agents"] == 0
    assert summary["disabled_agents"] == 1


def test_total_cost_usd_calculated_correctly(client: TestClient) -> None:
    agent = create_agent(client, "Cost Agent")
    create_execution(client, str(agent["id"]), cost_usd="1.25")
    create_execution(client, str(agent["id"]), cost_usd="2.75")
    create_execution(client, str(agent["id"]), cost_usd=None)

    summary = get_summary(client)

    assert Decimal(str(summary["total_cost_usd"])) == Decimal("4.0000")


def test_average_latency_ms_calculated_correctly(client: TestClient) -> None:
    agent = create_agent(client, "Latency Agent")
    create_execution(client, str(agent["id"]), latency_ms=100)
    create_execution(client, str(agent["id"]), latency_ms=300)
    create_execution(client, str(agent["id"]), latency_ms=None)

    summary = get_summary(client)

    assert summary["average_latency_ms"] == 200.0


def test_agents_by_risk_returns_all_risk_levels_with_zero_defaults(client: TestClient) -> None:
    create_agent(client, "Low Agent", risk_level="low")
    create_agent(client, "Critical Agent", risk_level="critical")

    response = client.get("/api/v1/dashboard/agents-by-risk")

    assert response.status_code == 200
    assert response.json() == {"low": 1, "medium": 0, "high": 0, "critical": 1}


def test_executions_by_status_returns_all_statuses_with_zero_defaults(client: TestClient) -> None:
    agent = create_agent(client, "Execution Status Agent")
    create_execution(client, str(agent["id"]), status="succeeded")
    create_execution(client, str(agent["id"]), status="running")

    response = client.get("/api/v1/dashboard/executions-by-status")

    assert response.status_code == 200
    assert response.json() == {
        "pending": 0,
        "running": 1,
        "succeeded": 1,
        "failed": 0,
        "blocked": 0,
        "requires_approval": 0,
    }


def test_approvals_by_status_returns_all_statuses_with_zero_defaults(client: TestClient) -> None:
    agent = create_agent(client, "Approval Status Agent")
    approved = create_approval(client, str(agent["id"]))
    client.post(f"/api/v1/approvals/{approved['id']}/approve")

    response = client.get("/api/v1/dashboard/approvals-by-status")

    assert response.status_code == 200
    assert response.json() == {
        "pending": 0,
        "approved": 1,
        "rejected": 0,
        "cancelled": 0,
    }
