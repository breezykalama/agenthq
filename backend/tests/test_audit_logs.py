from typing import Any, cast

from fastapi.testclient import TestClient

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
