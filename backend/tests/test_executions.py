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


def execution_payload(
    agent_id: str,
    risk_level: str = "low",
    status: str | None = "succeeded",
    approval_id: str | None = None,
) -> dict[str, object]:
    payload: dict[str, object] = {
        "agent_id": agent_id,
        "action_name": "summarize_policy",
        "input_summary": "Policy document submitted.",
        "output_summary": "Policy summary produced.",
        "risk_level": risk_level,
        "cost_usd": "0.1250",
        "latency_ms": 250,
    }
    if status is not None:
        payload["status"] = status
    if approval_id is not None:
        payload["approval_id"] = approval_id
    return payload


def create_execution(
    client: TestClient,
    agent_id: str,
    risk_level: str = "low",
    status: str | None = "succeeded",
    approval_id: str | None = None,
) -> JsonResponse:
    response = client.post(
        "/api/v1/executions",
        json=execution_payload(
            agent_id,
            risk_level=risk_level,
            status=status,
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


def test_create_low_risk_execution(client: TestClient) -> None:
    agent = create_agent(client)

    execution = create_execution(client, str(agent["id"]))

    assert execution["agent_id"] == agent["id"]
    assert execution["risk_level"] == "low"
    assert execution["status"] == "succeeded"
    assert execution["completed_at"] is not None


def test_create_high_risk_execution_defaults_to_requires_approval(client: TestClient) -> None:
    agent = create_agent(client)

    execution = create_execution(client, str(agent["id"]), risk_level="high", status="running")

    assert execution["status"] == "requires_approval"
    assert execution["approval_id"] is None


def test_create_critical_risk_execution_defaults_to_requires_approval(client: TestClient) -> None:
    agent = create_agent(client)

    execution = create_execution(client, str(agent["id"]), risk_level="critical", status=None)

    assert execution["status"] == "requires_approval"


def test_create_execution_with_approved_approval(client: TestClient) -> None:
    agent = create_agent(client)
    approval = approve_approval(client, str(create_approval(client, str(agent["id"]))["id"]))

    execution = create_execution(
        client,
        str(agent["id"]),
        risk_level="high",
        status="succeeded",
        approval_id=str(approval["id"]),
    )

    assert execution["status"] == "succeeded"
    assert execution["approval_id"] == approval["id"]


def test_reject_execution_with_unapproved_approval(client: TestClient) -> None:
    agent = create_agent(client)
    approval = create_approval(client, str(agent["id"]))

    response = client.post(
        "/api/v1/executions",
        json=execution_payload(
            str(agent["id"]),
            risk_level="high",
            status="succeeded",
            approval_id=str(approval["id"]),
        ),
    )

    assert response.status_code == 409


def test_reject_execution_with_approval_belonging_to_another_agent(client: TestClient) -> None:
    first_agent = create_agent(client, "Policy Review Agent")
    second_agent = create_agent(client, "Procurement Triage Agent")
    approval = approve_approval(client, str(create_approval(client, str(first_agent["id"]))["id"]))

    response = client.post(
        "/api/v1/executions",
        json=execution_payload(
            str(second_agent["id"]),
            risk_level="high",
            status="succeeded",
            approval_id=str(approval["id"]),
        ),
    )

    assert response.status_code == 409


def test_list_executions(client: TestClient) -> None:
    first_agent = create_agent(client, "Policy Review Agent")
    second_agent = create_agent(client, "Procurement Triage Agent")
    create_execution(client, str(first_agent["id"]))
    create_execution(client, str(second_agent["id"]), risk_level="medium", status="running")

    response = client.get("/api/v1/executions")

    assert response.status_code == 200
    data = response.json()
    assert data["total"] == 2
    assert {execution["risk_level"] for execution in data["items"]} == {"low", "medium"}


def test_get_execution_by_id(client: TestClient) -> None:
    agent = create_agent(client)
    execution = create_execution(client, str(agent["id"]))

    response = client.get(f"/api/v1/executions/{execution['id']}")

    assert response.status_code == 200
    assert response.json()["id"] == execution["id"]


def test_update_execution(client: TestClient) -> None:
    agent = create_agent(client)
    execution = create_execution(client, str(agent["id"]), status="running")

    response = client.patch(
        f"/api/v1/executions/{execution['id']}",
        json={"output_summary": "Updated output.", "latency_ms": 500},
    )

    assert response.status_code == 200
    data = response.json()
    assert data["output_summary"] == "Updated output."
    assert data["latency_ms"] == 500


def test_completed_at_set_when_terminal_status(client: TestClient) -> None:
    agent = create_agent(client)
    execution = create_execution(client, str(agent["id"]), status="running")

    response = client.patch(f"/api/v1/executions/{execution['id']}", json={"status": "failed"})

    assert response.status_code == 200
    assert response.json()["completed_at"] is not None


def test_negative_latency_rejected(client: TestClient) -> None:
    agent = create_agent(client)

    response = client.post(
        "/api/v1/executions",
        json={**execution_payload(str(agent["id"])), "latency_ms": -1},
    )

    assert response.status_code == 422


def test_negative_cost_rejected(client: TestClient) -> None:
    agent = create_agent(client)

    response = client.post(
        "/api/v1/executions",
        json={**execution_payload(str(agent["id"])), "cost_usd": "-0.01"},
    )

    assert response.status_code == 422


def test_cannot_create_execution_for_soft_deleted_agent(client: TestClient) -> None:
    agent = create_agent(client)
    client.delete(f"/api/v1/agents/{agent['id']}")

    response = client.post("/api/v1/executions", json=execution_payload(str(agent["id"])))

    assert response.status_code == 404


def test_filter_executions_by_agent_id(client: TestClient) -> None:
    first_agent = create_agent(client, "Policy Review Agent")
    second_agent = create_agent(client, "Procurement Triage Agent")
    first_execution = create_execution(client, str(first_agent["id"]))
    create_execution(client, str(second_agent["id"]))

    response = client.get("/api/v1/executions", params={"agent_id": first_agent["id"]})

    assert response.status_code == 200
    data = response.json()
    assert data["total"] == 1
    assert data["items"][0]["id"] == first_execution["id"]


def test_filter_executions_by_status(client: TestClient) -> None:
    first_agent = create_agent(client, "Policy Review Agent")
    second_agent = create_agent(client, "Procurement Triage Agent")
    create_execution(client, str(first_agent["id"]), status="succeeded")
    running_execution = create_execution(client, str(second_agent["id"]), status="running")

    response = client.get("/api/v1/executions", params={"status": "running"})

    assert response.status_code == 200
    data = response.json()
    assert data["total"] == 1
    assert data["items"][0]["id"] == running_execution["id"]


def test_audit_log_created_after_execution_create(client: TestClient) -> None:
    agent = create_agent(client)
    execution = create_execution(client, str(agent["id"]))

    logs = audit_logs(client, "execution.created")

    assert len(logs) == 1
    assert logs[0]["entity_type"] == "execution"
    assert logs[0]["entity_id"] == execution["id"]
    assert logs[0]["before"] is None
    assert logs[0]["after"]["status"] == "succeeded"


def test_audit_log_created_after_execution_update(client: TestClient) -> None:
    agent = create_agent(client)
    execution = create_execution(client, str(agent["id"]), status="running")

    client.patch(f"/api/v1/executions/{execution['id']}", json={"status": "blocked"})
    logs = audit_logs(client, "execution.updated")

    assert len(logs) == 1
    assert logs[0]["before"]["status"] == "running"
    assert logs[0]["after"]["status"] == "blocked"
    assert logs[0]["after"]["completed_at"] is not None


def test_execution_state_changes_create_semantic_audit_events(client: TestClient) -> None:
    agent = create_agent(client)
    execution = create_execution(client, str(agent["id"]), status="running")

    client.patch(f"/api/v1/executions/{execution['id']}", json={"status": "failed"})

    started = audit_logs(client, "execution.started")
    failed = audit_logs(client, "execution.failed")
    assert len(started) == 1
    assert started[0]["entity_id"] == execution["id"]
    assert len(failed) == 1
    assert failed[0]["entity_id"] == execution["id"]
    assert failed[0]["outcome"] == "failed"
