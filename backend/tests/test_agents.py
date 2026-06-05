from typing import cast
from uuid import UUID

from fastapi.testclient import TestClient


def agent_payload(name: str = "Policy Review Agent") -> dict[str, str]:
    return {
        "name": name,
        "description": "Reviews internal policy drafts.",
        "owner": "platform-team",
        "department": "governance",
        "risk_level": "medium",
        "status": "draft",
    }


def create_agent(client: TestClient, name: str = "Policy Review Agent") -> dict[str, object]:
    response = client.post("/api/v1/agents", json=agent_payload(name=name))
    assert response.status_code == 201
    return cast(dict[str, object], response.json())


def test_create_agent(client: TestClient) -> None:
    data = create_agent(client)

    assert UUID(str(data["id"]))
    assert data["name"] == "Policy Review Agent"
    assert data["risk_level"] == "medium"
    assert data["status"] == "draft"
    assert data["deleted_at"] is None


def test_list_agents(client: TestClient) -> None:
    create_agent(client, "Policy Review Agent")
    create_agent(client, "Procurement Triage Agent")

    response = client.get("/api/v1/agents")

    assert response.status_code == 200
    data = response.json()
    assert data["total"] == 2
    assert {agent["name"] for agent in data["items"]} == {
        "Policy Review Agent",
        "Procurement Triage Agent",
    }


def test_get_agent_by_id(client: TestClient) -> None:
    created_agent = create_agent(client)

    response = client.get(f"/api/v1/agents/{created_agent['id']}")

    assert response.status_code == 200
    assert response.json()["id"] == created_agent["id"]


def test_update_agent(client: TestClient) -> None:
    created_agent = create_agent(client)

    response = client.patch(
        f"/api/v1/agents/{created_agent['id']}",
        json={"status": "active", "risk_level": "high"},
    )

    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "active"
    assert data["risk_level"] == "high"


def test_soft_delete_agent(client: TestClient) -> None:
    created_agent = create_agent(client)

    response = client.delete(f"/api/v1/agents/{created_agent['id']}")

    assert response.status_code == 204


def test_soft_deleted_agent_not_returned_in_list(client: TestClient) -> None:
    deleted_agent = create_agent(client, "Policy Review Agent")
    visible_agent = create_agent(client, "Procurement Triage Agent")
    client.delete(f"/api/v1/agents/{deleted_agent['id']}")

    response = client.get("/api/v1/agents")

    assert response.status_code == 200
    data = response.json()
    assert data["total"] == 1
    assert data["items"][0]["id"] == visible_agent["id"]


def test_soft_deleted_agent_returns_404_on_get(client: TestClient) -> None:
    created_agent = create_agent(client)
    client.delete(f"/api/v1/agents/{created_agent['id']}")

    response = client.get(f"/api/v1/agents/{created_agent['id']}")

    assert response.status_code == 404


def test_duplicate_non_deleted_agent_name_returns_409(client: TestClient) -> None:
    create_agent(client)

    response = client.post("/api/v1/agents", json=agent_payload())

    assert response.status_code == 409


def test_same_name_can_be_reused_after_soft_delete(client: TestClient) -> None:
    created_agent = create_agent(client)
    client.delete(f"/api/v1/agents/{created_agent['id']}")

    response = client.post("/api/v1/agents", json=agent_payload())

    assert response.status_code == 201
