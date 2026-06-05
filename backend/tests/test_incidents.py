from typing import Any, cast

from fastapi.testclient import TestClient

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


def create_execution(client: TestClient, agent_id: str) -> JsonResponse:
    response = client.post(
        "/api/v1/executions",
        json={
            "agent_id": agent_id,
            "action_name": "summarize_policy",
            "risk_level": "low",
            "status": "failed",
        },
    )
    assert response.status_code == 201
    return cast(JsonResponse, response.json())


def incident_payload(
    agent_id: str,
    execution_id: str | None = None,
    title: str = "Failed execution",
    severity: str = "high",
) -> dict[str, object]:
    payload: dict[str, object] = {
        "agent_id": agent_id,
        "title": title,
        "description": "The execution failed unexpectedly.",
        "severity": severity,
        "reported_by": "auditor",
    }
    if execution_id is not None:
        payload["execution_id"] = execution_id
    return payload


def create_incident(
    client: TestClient,
    agent_id: str,
    execution_id: str | None = None,
    title: str = "Failed execution",
    severity: str = "high",
) -> JsonResponse:
    response = client.post(
        "/api/v1/incidents",
        json=incident_payload(
            agent_id,
            execution_id=execution_id,
            title=title,
            severity=severity,
        ),
    )
    assert response.status_code == 201
    return cast(JsonResponse, response.json())


def audit_logs(client: TestClient, action: str) -> list[JsonResponse]:
    response = client.get("/api/v1/audit-logs", params={"action": action})
    assert response.status_code == 200
    data = cast(JsonResponse, response.json())
    return cast(list[JsonResponse], data["items"])


def test_create_incident(client: TestClient) -> None:
    agent = create_agent(client)

    incident = create_incident(client, str(agent["id"]))

    assert incident["agent_id"] == agent["id"]
    assert incident["execution_id"] is None
    assert incident["status"] == "open"
    assert incident["reported_by"] == "auditor"


def test_create_incident_linked_to_execution(client: TestClient) -> None:
    agent = create_agent(client)
    execution = create_execution(client, str(agent["id"]))

    incident = create_incident(client, str(agent["id"]), execution_id=str(execution["id"]))

    assert incident["execution_id"] == execution["id"]


def test_reject_execution_from_different_agent(client: TestClient) -> None:
    first_agent = create_agent(client, "Policy Review Agent")
    second_agent = create_agent(client, "Procurement Triage Agent")
    execution = create_execution(client, str(first_agent["id"]))

    response = client.post(
        "/api/v1/incidents",
        json=incident_payload(str(second_agent["id"]), execution_id=str(execution["id"])),
    )

    assert response.status_code == 422


def test_list_incidents(client: TestClient) -> None:
    agent = create_agent(client)
    create_incident(client, str(agent["id"]), title="First incident")
    create_incident(client, str(agent["id"]), title="Second incident")

    response = client.get("/api/v1/incidents")

    assert response.status_code == 200
    data = response.json()
    assert data["total"] == 2
    assert {incident["title"] for incident in data["items"]} == {
        "First incident",
        "Second incident",
    }


def test_filter_incidents_by_status(client: TestClient) -> None:
    agent = create_agent(client)
    create_incident(client, str(agent["id"]), title="Open incident")
    investigating = create_incident(client, str(agent["id"]), title="Investigating incident")
    client.patch(f"/api/v1/incidents/{investigating['id']}", json={"status": "investigating"})

    response = client.get("/api/v1/incidents", params={"status": "investigating"})

    assert response.status_code == 200
    data = response.json()
    assert data["total"] == 1
    assert data["items"][0]["id"] == investigating["id"]


def test_filter_incidents_by_severity(client: TestClient) -> None:
    agent = create_agent(client)
    critical = create_incident(
        client,
        str(agent["id"]),
        title="Critical incident",
        severity="critical",
    )
    create_incident(client, str(agent["id"]), title="Low incident", severity="low")

    response = client.get("/api/v1/incidents", params={"severity": "critical"})

    assert response.status_code == 200
    data = response.json()
    assert data["total"] == 1
    assert data["items"][0]["id"] == critical["id"]


def test_update_incident_assignment(client: TestClient) -> None:
    agent = create_agent(client)
    incident = create_incident(client, str(agent["id"]))

    response = client.patch(f"/api/v1/incidents/{incident['id']}", json={"assigned_to": "ops"})

    assert response.status_code == 200
    assert response.json()["assigned_to"] == "ops"


def test_resolve_incident_with_resolution_notes(client: TestClient) -> None:
    agent = create_agent(client)
    incident = create_incident(client, str(agent["id"]))

    response = client.post(
        f"/api/v1/incidents/{incident['id']}/resolve",
        json={"resolution_notes": "Issue remediated."},
    )

    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "resolved"
    assert data["resolved_at"] is not None
    assert data["resolution_notes"] == "Issue remediated."


def test_reject_resolve_without_resolution_notes(client: TestClient) -> None:
    agent = create_agent(client)
    incident = create_incident(client, str(agent["id"]))

    response = client.post(f"/api/v1/incidents/{incident['id']}/resolve")

    assert response.status_code == 422


def test_dismiss_incident(client: TestClient) -> None:
    agent = create_agent(client)
    incident = create_incident(client, str(agent["id"]))

    response = client.post(
        f"/api/v1/incidents/{incident['id']}/dismiss",
        json={"resolution_notes": "False positive."},
    )

    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "dismissed"
    assert data["resolved_at"] is not None


def test_cannot_reopen_resolved_incident(client: TestClient) -> None:
    agent = create_agent(client)
    incident = create_incident(client, str(agent["id"]))
    client.post(
        f"/api/v1/incidents/{incident['id']}/resolve",
        json={"resolution_notes": "Issue remediated."},
    )

    response = client.patch(f"/api/v1/incidents/{incident['id']}", json={"status": "open"})

    assert response.status_code == 409


def test_audit_log_created_after_incident_create(client: TestClient) -> None:
    agent = create_agent(client)
    incident = create_incident(client, str(agent["id"]))

    logs = audit_logs(client, "incident.created")

    assert len(logs) == 1
    assert logs[0]["entity_type"] == "incident"
    assert logs[0]["entity_id"] == incident["id"]
    assert logs[0]["before"] is None
    assert logs[0]["after"]["title"] == "Failed execution"


def test_audit_log_created_after_incident_update(client: TestClient) -> None:
    agent = create_agent(client)
    incident = create_incident(client, str(agent["id"]))

    client.patch(f"/api/v1/incidents/{incident['id']}", json={"assigned_to": "ops"})
    logs = audit_logs(client, "incident.updated")

    assert len(logs) == 1
    assert logs[0]["before"]["assigned_to"] is None
    assert logs[0]["after"]["assigned_to"] == "ops"


def test_audit_log_created_after_incident_resolve(client: TestClient) -> None:
    agent = create_agent(client)
    incident = create_incident(client, str(agent["id"]))

    client.post(
        f"/api/v1/incidents/{incident['id']}/resolve",
        json={"resolution_notes": "Issue remediated."},
    )
    logs = audit_logs(client, "incident.resolved")

    assert len(logs) == 1
    assert logs[0]["before"]["status"] == "open"
    assert logs[0]["after"]["status"] == "resolved"


def test_audit_log_created_after_incident_dismiss(client: TestClient) -> None:
    agent = create_agent(client)
    incident = create_incident(client, str(agent["id"]))

    client.post(f"/api/v1/incidents/{incident['id']}/dismiss")
    logs = audit_logs(client, "incident.dismissed")

    assert len(logs) == 1
    assert logs[0]["before"]["status"] == "open"
    assert logs[0]["after"]["status"] == "dismissed"
