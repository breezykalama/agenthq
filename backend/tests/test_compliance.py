from datetime import UTC, datetime, timedelta
from typing import Any, cast

from fastapi.testclient import TestClient

JsonResponse = dict[str, Any]


def today() -> str:
    return datetime.now(UTC).date().isoformat()


def yesterday() -> str:
    return (datetime.now(UTC).date() - timedelta(days=1)).isoformat()


def tomorrow() -> str:
    return (datetime.now(UTC).date() + timedelta(days=1)).isoformat()


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


def create_tool(client: TestClient, agent_id: str) -> JsonResponse:
    response = client.post(
        f"/api/v1/agents/{agent_id}/tools",
        json={
            "name": "document_search",
            "description": "Search internal policy documents.",
            "permission": "read",
            "risk_level": "low",
        },
    )
    assert response.status_code == 201
    return cast(JsonResponse, response.json())


def create_policy_rule(client: TestClient, agent_id: str) -> JsonResponse:
    response = client.post(
        "/api/v1/policy-rules",
        json={
            "name": "Agent block rule",
            "scope": "agent",
            "agent_id": agent_id,
            "risk_level": "low",
            "effect": "block",
        },
    )
    assert response.status_code == 201
    return cast(JsonResponse, response.json())


def create_execution(
    client: TestClient,
    agent_id: str,
    status: str = "failed",
    risk_level: str = "low",
) -> JsonResponse:
    response = client.post(
        "/api/v1/executions",
        json={
            "agent_id": agent_id,
            "action_name": "summarize_policy",
            "risk_level": risk_level,
            "status": status,
        },
    )
    assert response.status_code == 201
    return cast(JsonResponse, response.json())


def create_approval(client: TestClient, agent_id: str) -> JsonResponse:
    response = client.post(
        "/api/v1/approvals",
        json={
            "agent_id": agent_id,
            "requested_action": "activate_agent",
            "risk_level": "high",
        },
    )
    assert response.status_code == 201
    return cast(JsonResponse, response.json())


def create_incident(
    client: TestClient,
    agent_id: str,
    execution_id: str | None = None,
    severity: str = "critical",
    status: str = "open",
    title: str = "Compliance incident",
) -> JsonResponse:
    payload: dict[str, object] = {
        "agent_id": agent_id,
        "title": title,
        "description": "Incident for compliance reporting.",
        "severity": severity,
        "status": status,
        "reported_by": "auditor",
    }
    if execution_id is not None:
        payload["execution_id"] = execution_id
    response = client.post("/api/v1/incidents", json=payload)
    assert response.status_code == 201
    return cast(JsonResponse, response.json())


def test_compliance_summary_empty_state(client: TestClient) -> None:
    response = client.get("/api/v1/compliance/summary")

    assert response.status_code == 200
    assert response.json() == {
        "total_agents": 0,
        "total_executions": 0,
        "blocked_executions": 0,
        "executions_requiring_approval": 0,
        "approved_approvals": 0,
        "rejected_approvals": 0,
        "open_incidents": 0,
        "critical_incidents": 0,
        "policy_decisions_evaluated": 0,
        "audit_events": 0,
    }


def test_compliance_summary_with_populated_data(client: TestClient) -> None:
    agent = create_agent(client)
    create_execution(client, str(agent["id"]), status="succeeded", risk_level="high")
    create_policy_rule(client, str(agent["id"]))
    create_execution(client, str(agent["id"]), status="succeeded")
    approved = create_approval(client, str(agent["id"]))
    rejected = create_approval(client, str(agent["id"]))
    client.post(f"/api/v1/approvals/{approved['id']}/approve")
    client.post(f"/api/v1/approvals/{rejected['id']}/reject")
    create_incident(client, str(agent["id"]), severity="critical")

    response = client.get("/api/v1/compliance/summary")

    assert response.status_code == 200
    data = response.json()
    assert data["total_agents"] == 1
    assert data["total_executions"] == 2
    assert data["blocked_executions"] == 1
    assert data["executions_requiring_approval"] == 1
    assert data["approved_approvals"] == 1
    assert data["rejected_approvals"] == 1
    assert data["open_incidents"] == 1
    assert data["critical_incidents"] == 1
    assert data["policy_decisions_evaluated"] == 2
    assert data["audit_events"] >= 1


def test_compliance_summary_date_filtering(client: TestClient) -> None:
    agent = create_agent(client)
    create_execution(client, str(agent["id"]))

    today_response = client.get("/api/v1/compliance/summary", params={"start_date": today()})
    tomorrow_response = client.get("/api/v1/compliance/summary", params={"start_date": tomorrow()})

    assert today_response.status_code == 200
    assert tomorrow_response.status_code == 200
    assert today_response.json()["total_executions"] == 1
    assert tomorrow_response.json()["total_executions"] == 0


def test_compliance_summary_rejects_invalid_date_range(client: TestClient) -> None:
    response = client.get(
        "/api/v1/compliance/summary",
        params={"start_date": tomorrow(), "end_date": yesterday()},
    )

    assert response.status_code == 422


def test_agent_compliance_report(client: TestClient) -> None:
    agent = create_agent(client)
    create_tool(client, str(agent["id"]))
    execution = create_execution(client, str(agent["id"]))
    create_policy_rule(client, str(agent["id"]))
    create_approval(client, str(agent["id"]))
    create_incident(client, str(agent["id"]), execution_id=str(execution["id"]))

    response = client.get(f"/api/v1/compliance/agent/{agent['id']}")

    assert response.status_code == 200
    data = response.json()
    assert data["agent"]["id"] == agent["id"]
    assert data["tools_count"] == 1
    assert data["policy_rules_count"] == 1
    assert data["executions_count"] == 1
    assert data["failed_executions"] == 1
    assert data["approvals_count"] == 1
    assert data["incidents_count"] == 1
    assert data["latest_execution_at"] is not None
    assert data["latest_incident_at"] is not None


def test_agent_compliance_report_rejects_soft_deleted_agent(client: TestClient) -> None:
    agent = create_agent(client)
    client.delete(f"/api/v1/agents/{agent['id']}")

    response = client.get(f"/api/v1/compliance/agent/{agent['id']}")

    assert response.status_code == 404


def test_incidents_report_filters_by_severity(client: TestClient) -> None:
    agent = create_agent(client)
    critical = create_incident(client, str(agent["id"]), severity="critical", title="Critical")
    create_incident(client, str(agent["id"]), severity="low", title="Low")

    response = client.get("/api/v1/compliance/incidents", params={"severity": "critical"})

    assert response.status_code == 200
    data = response.json()
    assert data["total"] == 1
    assert data["items"][0]["id"] == critical["id"]


def test_incidents_report_filters_by_status(client: TestClient) -> None:
    agent = create_agent(client)
    investigating = create_incident(
        client,
        str(agent["id"]),
        status="investigating",
        title="Investigating",
    )
    create_incident(client, str(agent["id"]), status="open", title="Open")

    response = client.get("/api/v1/compliance/incidents", params={"status": "investigating"})

    assert response.status_code == 200
    data = response.json()
    assert data["total"] == 1
    assert data["items"][0]["id"] == investigating["id"]


def test_incidents_report_filters_by_agent_id(client: TestClient) -> None:
    first_agent = create_agent(client, "Policy Review Agent")
    second_agent = create_agent(client, "Procurement Triage Agent")
    incident = create_incident(client, str(first_agent["id"]))
    create_incident(client, str(second_agent["id"]))

    response = client.get("/api/v1/compliance/incidents", params={"agent_id": first_agent["id"]})

    assert response.status_code == 200
    data = response.json()
    assert data["total"] == 1
    assert data["items"][0]["id"] == incident["id"]


def test_incidents_report_date_filtering(client: TestClient) -> None:
    agent = create_agent(client)
    create_incident(client, str(agent["id"]))

    today_response = client.get("/api/v1/compliance/incidents", params={"start_date": today()})
    tomorrow_response = client.get(
        "/api/v1/compliance/incidents",
        params={"start_date": tomorrow()},
    )

    assert today_response.status_code == 200
    assert tomorrow_response.status_code == 200
    assert today_response.json()["total"] == 1
    assert tomorrow_response.json()["total"] == 0


def test_compliance_report_access_is_audited(client: TestClient) -> None:
    response = client.get(
        "/api/v1/compliance/summary",
        headers={"X-Request-ID": "compliance-audit-request"},
    )
    audits = client.get(
        "/api/v1/audit-logs",
        params={"action": "compliance.report_accessed"},
    ).json()

    assert response.status_code == 200
    assert audits["total"] == 1
    assert audits["items"][0]["resource_type"] == "compliance_summary"
    assert audits["items"][0]["request_id"] == "compliance-audit-request"
