from typing import Any, cast

from fastapi.testclient import TestClient

JsonResponse = dict[str, Any]


def agent_payload(name: str = "Policy Review Agent") -> dict[str, str]:
    return {
        "name": name,
        "description": "Reviews internal policy drafts.",
        "owner": "platform-team",
        "department": "governance",
        "risk_level": "high",
        "status": "draft",
    }


def create_agent(client: TestClient, name: str = "Policy Review Agent") -> JsonResponse:
    response = client.post("/api/v1/agents", json=agent_payload(name=name))
    assert response.status_code == 201
    return cast(JsonResponse, response.json())


def approval_payload(agent_id: str, risk_level: str = "high") -> dict[str, str]:
    return {
        "agent_id": agent_id,
        "requested_action": "activate_agent",
        "requested_by": "platform-team",
        "reason": "High-risk agent activation requires review.",
        "risk_level": risk_level,
    }


def create_approval(
    client: TestClient,
    agent_id: str,
    risk_level: str = "high",
) -> JsonResponse:
    response = client.post(
        "/api/v1/approvals",
        json=approval_payload(agent_id, risk_level=risk_level),
    )
    assert response.status_code == 201
    return cast(JsonResponse, response.json())


def audit_logs(client: TestClient, action: str) -> list[JsonResponse]:
    response = client.get("/api/v1/audit-logs", params={"action": action})
    assert response.status_code == 200
    data = cast(JsonResponse, response.json())
    return cast(list[JsonResponse], data["items"])


def test_create_approval(client: TestClient) -> None:
    agent = create_agent(client)

    approval = create_approval(client, str(agent["id"]))

    assert approval["agent_id"] == agent["id"]
    assert approval["requested_action"] == "activate_agent"
    assert approval["requested_by"] == "platform-team"
    assert approval["status"] == "pending"
    assert approval["risk_level"] == "high"
    assert approval["approver"] is None
    assert approval["decided_at"] is None


def test_list_approvals(client: TestClient) -> None:
    first_agent = create_agent(client, "Policy Review Agent")
    second_agent = create_agent(client, "Procurement Triage Agent")
    create_approval(client, str(first_agent["id"]))
    create_approval(client, str(second_agent["id"]), risk_level="critical")

    response = client.get("/api/v1/approvals")

    assert response.status_code == 200
    data = response.json()
    assert data["total"] == 2
    assert {approval["risk_level"] for approval in data["items"]} == {"high", "critical"}


def test_get_approval_by_id(client: TestClient) -> None:
    agent = create_agent(client)
    approval = create_approval(client, str(agent["id"]))

    response = client.get(f"/api/v1/approvals/{approval['id']}")

    assert response.status_code == 200
    assert response.json()["id"] == approval["id"]


def test_approve_pending_approval(client: TestClient) -> None:
    agent = create_agent(client)
    approval = create_approval(client, str(agent["id"]))

    response = client.post(
        f"/api/v1/approvals/{approval['id']}/approve",
        json={"approver": "risk-office", "decision_reason": "Controls are sufficient."},
    )

    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "approved"
    assert data["approver"] == "risk-office"
    assert data["decision_reason"] == "Controls are sufficient."
    assert data["decided_at"] is not None


def test_reject_pending_approval(client: TestClient) -> None:
    agent = create_agent(client)
    approval = create_approval(client, str(agent["id"]))

    response = client.post(
        f"/api/v1/approvals/{approval['id']}/reject",
        json={"approver": "risk-office", "decision_reason": "Missing owner attestation."},
    )

    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "rejected"
    assert data["approver"] == "risk-office"


def test_cancel_pending_approval(client: TestClient) -> None:
    agent = create_agent(client)
    approval = create_approval(client, str(agent["id"]))

    response = client.post(
        f"/api/v1/approvals/{approval['id']}/cancel",
        json={"decision_reason": "Request withdrawn."},
    )

    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "cancelled"
    assert data["decision_reason"] == "Request withdrawn."


def test_cannot_approve_rejected_approval(client: TestClient) -> None:
    agent = create_agent(client)
    approval = create_approval(client, str(agent["id"]))
    client.post(f"/api/v1/approvals/{approval['id']}/reject")

    response = client.post(f"/api/v1/approvals/{approval['id']}/approve")

    assert response.status_code == 409


def test_cannot_reject_approved_approval(client: TestClient) -> None:
    agent = create_agent(client)
    approval = create_approval(client, str(agent["id"]))
    client.post(f"/api/v1/approvals/{approval['id']}/approve")

    response = client.post(f"/api/v1/approvals/{approval['id']}/reject")

    assert response.status_code == 409


def test_cannot_approve_cancelled_approval(client: TestClient) -> None:
    agent = create_agent(client)
    approval = create_approval(client, str(agent["id"]))
    client.post(f"/api/v1/approvals/{approval['id']}/cancel")

    response = client.post(f"/api/v1/approvals/{approval['id']}/approve")

    assert response.status_code == 409


def test_cannot_create_approval_for_soft_deleted_agent(client: TestClient) -> None:
    agent = create_agent(client)
    client.delete(f"/api/v1/agents/{agent['id']}")

    response = client.post("/api/v1/approvals", json=approval_payload(str(agent["id"])))

    assert response.status_code == 404


def test_filter_approvals_by_status(client: TestClient) -> None:
    first_agent = create_agent(client, "Policy Review Agent")
    second_agent = create_agent(client, "Procurement Triage Agent")
    approved = create_approval(client, str(first_agent["id"]))
    create_approval(client, str(second_agent["id"]))
    client.post(f"/api/v1/approvals/{approved['id']}/approve")

    response = client.get("/api/v1/approvals", params={"status": "approved"})

    assert response.status_code == 200
    data = response.json()
    assert data["total"] == 1
    assert data["items"][0]["id"] == approved["id"]


def test_filter_approvals_by_risk_level(client: TestClient) -> None:
    first_agent = create_agent(client, "Policy Review Agent")
    second_agent = create_agent(client, "Procurement Triage Agent")
    create_approval(client, str(first_agent["id"]), risk_level="high")
    critical = create_approval(client, str(second_agent["id"]), risk_level="critical")

    response = client.get("/api/v1/approvals", params={"risk_level": "critical"})

    assert response.status_code == 200
    data = response.json()
    assert data["total"] == 1
    assert data["items"][0]["id"] == critical["id"]


def test_audit_log_created_after_approval_create(client: TestClient) -> None:
    agent = create_agent(client)
    approval = create_approval(client, str(agent["id"]))

    logs = audit_logs(client, "approval.created")

    assert len(logs) == 1
    assert logs[0]["entity_type"] == "approval"
    assert logs[0]["entity_id"] == approval["id"]
    assert logs[0]["before"] is None
    assert logs[0]["after"]["status"] == "pending"


def test_audit_log_created_after_approval_approve(client: TestClient) -> None:
    agent = create_agent(client)
    approval = create_approval(client, str(agent["id"]))

    client.post(f"/api/v1/approvals/{approval['id']}/approve", json={"approver": "risk-office"})
    logs = audit_logs(client, "approval.approved")

    assert len(logs) == 1
    assert logs[0]["before"]["status"] == "pending"
    assert logs[0]["after"]["status"] == "approved"
    assert logs[0]["after"]["approver"] == "risk-office"


def test_audit_log_created_after_approval_reject(client: TestClient) -> None:
    agent = create_agent(client)
    approval = create_approval(client, str(agent["id"]))

    client.post(f"/api/v1/approvals/{approval['id']}/reject", json={"approver": "risk-office"})
    logs = audit_logs(client, "approval.rejected")

    assert len(logs) == 1
    assert logs[0]["before"]["status"] == "pending"
    assert logs[0]["after"]["status"] == "rejected"


def test_audit_log_created_after_approval_cancel(client: TestClient) -> None:
    agent = create_agent(client)
    approval = create_approval(client, str(agent["id"]))

    client.post(f"/api/v1/approvals/{approval['id']}/cancel")
    logs = audit_logs(client, "approval.cancelled")

    assert len(logs) == 1
    assert logs[0]["before"]["status"] == "pending"
    assert logs[0]["after"]["status"] == "cancelled"
