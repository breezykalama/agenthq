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


def tool_payload(name: str = "document_search") -> dict[str, object]:
    return {
        "name": name,
        "description": "Search internal policy documents.",
        "permission": "read",
        "risk_level": "low",
        "is_enabled": True,
    }


def create_tool(
    client: TestClient,
    agent_id: str,
    name: str = "document_search",
) -> JsonResponse:
    response = client.post(f"/api/v1/agents/{agent_id}/tools", json=tool_payload(name=name))
    assert response.status_code == 201
    return cast(JsonResponse, response.json())


def audit_logs(client: TestClient, action: str) -> list[JsonResponse]:
    response = client.get("/api/v1/audit-logs", params={"action": action})
    assert response.status_code == 200
    data = cast(JsonResponse, response.json())
    return cast(list[JsonResponse], data["items"])


def test_create_tool_for_agent(client: TestClient) -> None:
    agent = create_agent(client)

    tool = create_tool(client, str(agent["id"]))

    assert tool["agent_id"] == agent["id"]
    assert tool["name"] == "document_search"
    assert tool["permission"] == "read"
    assert tool["risk_level"] == "low"
    assert tool["is_enabled"] is True
    assert tool["deleted_at"] is None


def test_list_tools_for_agent(client: TestClient) -> None:
    agent = create_agent(client)
    create_tool(client, str(agent["id"]), "document_search")
    create_tool(client, str(agent["id"]), "ticket_update")

    response = client.get(f"/api/v1/agents/{agent['id']}/tools")

    assert response.status_code == 200
    data = response.json()
    assert data["total"] == 2
    assert {tool["name"] for tool in data["items"]} == {"document_search", "ticket_update"}


def test_get_tool_by_id(client: TestClient) -> None:
    agent = create_agent(client)
    tool = create_tool(client, str(agent["id"]))

    response = client.get(f"/api/v1/agents/{agent['id']}/tools/{tool['id']}")

    assert response.status_code == 200
    assert response.json()["id"] == tool["id"]


def test_update_tool(client: TestClient) -> None:
    agent = create_agent(client)
    tool = create_tool(client, str(agent["id"]))

    response = client.patch(
        f"/api/v1/agents/{agent['id']}/tools/{tool['id']}",
        json={"permission": "execute", "risk_level": "high"},
    )

    assert response.status_code == 200
    data = response.json()
    assert data["permission"] == "execute"
    assert data["risk_level"] == "high"


def test_soft_delete_tool(client: TestClient) -> None:
    agent = create_agent(client)
    tool = create_tool(client, str(agent["id"]))

    response = client.delete(f"/api/v1/agents/{agent['id']}/tools/{tool['id']}")

    assert response.status_code == 204


def test_soft_deleted_tool_excluded_from_list(client: TestClient) -> None:
    agent = create_agent(client)
    deleted_tool = create_tool(client, str(agent["id"]), "document_search")
    visible_tool = create_tool(client, str(agent["id"]), "ticket_update")
    client.delete(f"/api/v1/agents/{agent['id']}/tools/{deleted_tool['id']}")

    response = client.get(f"/api/v1/agents/{agent['id']}/tools")

    assert response.status_code == 200
    data = response.json()
    assert data["total"] == 1
    assert data["items"][0]["id"] == visible_tool["id"]


def test_duplicate_tool_name_for_same_agent_returns_409(client: TestClient) -> None:
    agent = create_agent(client)
    create_tool(client, str(agent["id"]))

    response = client.post(f"/api/v1/agents/{agent['id']}/tools", json=tool_payload())

    assert response.status_code == 409


def test_same_tool_name_allowed_across_different_agents(client: TestClient) -> None:
    first_agent = create_agent(client, "Policy Review Agent")
    second_agent = create_agent(client, "Procurement Triage Agent")
    create_tool(client, str(first_agent["id"]))

    response = client.post(f"/api/v1/agents/{second_agent['id']}/tools", json=tool_payload())

    assert response.status_code == 201


def test_cannot_create_tool_for_soft_deleted_agent(client: TestClient) -> None:
    agent = create_agent(client)
    client.delete(f"/api/v1/agents/{agent['id']}")

    response = client.post(f"/api/v1/agents/{agent['id']}/tools", json=tool_payload())

    assert response.status_code == 404


def test_disabled_tool_remains_visible(client: TestClient) -> None:
    agent = create_agent(client)
    tool = create_tool(client, str(agent["id"]))

    response = client.patch(
        f"/api/v1/agents/{agent['id']}/tools/{tool['id']}",
        json={"is_enabled": False},
    )
    assert response.status_code == 200

    list_response = client.get(f"/api/v1/agents/{agent['id']}/tools")
    data = list_response.json()
    assert data["total"] == 1
    assert data["items"][0]["is_enabled"] is False


def test_audit_log_created_after_tool_create(client: TestClient) -> None:
    agent = create_agent(client)
    tool = create_tool(client, str(agent["id"]))

    logs = audit_logs(client, "agent_tool.created")

    assert len(logs) == 1
    assert logs[0]["entity_type"] == "agent_tool"
    assert logs[0]["entity_id"] == tool["id"]
    assert logs[0]["before"] is None
    assert logs[0]["after"]["name"] == "document_search"


def test_audit_log_created_after_tool_update(client: TestClient) -> None:
    agent = create_agent(client)
    tool = create_tool(client, str(agent["id"]))

    client.patch(f"/api/v1/agents/{agent['id']}/tools/{tool['id']}", json={"name": "web_search"})
    logs = audit_logs(client, "agent_tool.updated")

    assert len(logs) == 1
    assert logs[0]["before"]["name"] == "document_search"
    assert logs[0]["after"]["name"] == "web_search"


def test_audit_log_created_after_tool_delete(client: TestClient) -> None:
    agent = create_agent(client)
    tool = create_tool(client, str(agent["id"]))

    client.delete(f"/api/v1/agents/{agent['id']}/tools/{tool['id']}")
    logs = audit_logs(client, "agent_tool.deleted")

    assert len(logs) == 1
    assert logs[0]["before"]["deleted_at"] is None
    assert logs[0]["after"]["deleted_at"] is not None
