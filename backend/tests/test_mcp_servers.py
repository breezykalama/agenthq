from typing import Any, cast

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.adapters.mcp_discovery import get_mcp_discovery_adapter
from app.core.config import get_settings
from app.schemas.mcp_server import MCPServerCreate

JsonResponse = dict[str, Any]


def mcp_server_payload(name: str = "Knowledge MCP") -> dict[str, object]:
    return {
        "name": name,
        "description": "Provides governed knowledge tools.",
        "server_url": "https://mcp.example.com/server",
    }


def create_mcp_server(client: TestClient, name: str = "Knowledge MCP") -> JsonResponse:
    response = client.post("/api/v1/mcp-servers", json=mcp_server_payload(name))
    assert response.status_code == 201
    return cast(JsonResponse, response.json())


def sync_mcp_server(client: TestClient, server_id: str) -> JsonResponse:
    response = client.post(f"/api/v1/mcp-servers/{server_id}/sync")
    assert response.status_code == 200
    return cast(JsonResponse, response.json())


def audit_logs(client: TestClient, action: str) -> list[JsonResponse]:
    response = client.get("/api/v1/audit-logs", params={"action": action})
    assert response.status_code == 200
    return cast(list[JsonResponse], response.json()["items"])


def test_create_mcp_server(client: TestClient) -> None:
    mcp_server = create_mcp_server(client)

    assert mcp_server["name"] == "Knowledge MCP"
    assert mcp_server["server_url"] == "https://mcp.example.com/server"
    assert mcp_server["status"] == "disconnected"
    assert mcp_server["last_sync_at"] is None
    assert mcp_server["deleted_at"] is None


def test_create_mcp_server_with_real_discovery_configuration(client: TestClient) -> None:
    payload = mcp_server_payload()
    payload.update(
        {
            "transport_type": "sse",
            "auth_type": "bearer",
            "auth_secret_ref": "MCP_AUTH_CUSTOMER_OPERATIONS",
            "request_timeout_seconds": 45,
            "connect_timeout_seconds": 8,
        }
    )

    response = client.post("/api/v1/mcp-servers", json=payload)

    assert response.status_code == 201
    assert response.json()["transport_type"] == "sse"
    assert response.json()["auth_type"] == "bearer"
    assert response.json()["auth_secret_ref"] == "MCP_AUTH_CUSTOMER_OPERATIONS"
    assert response.json()["request_timeout_seconds"] == 45
    assert response.json()["connect_timeout_seconds"] == 8


@pytest.mark.parametrize(
    "payload_update",
    [
        {"auth_type": "bearer"},
        {"auth_type": "api_key", "auth_secret_ref": "DATABASE_URL"},
        {"auth_type": "none", "auth_secret_ref": "MCP_AUTH_UNUSED"},
    ],
)
def test_create_mcp_server_rejects_unsafe_auth_configuration(
    client: TestClient,
    payload_update: dict[str, object],
) -> None:
    payload = mcp_server_payload()
    payload.update(payload_update)

    response = client.post("/api/v1/mcp-servers", json=payload)

    assert response.status_code == 422


def test_update_mcp_server_rejects_incomplete_auth_configuration(client: TestClient) -> None:
    mcp_server = create_mcp_server(client)

    response = client.patch(
        f"/api/v1/mcp-servers/{mcp_server['id']}",
        json={"auth_type": "bearer"},
    )

    assert response.status_code == 422
    assert response.json()["detail"] == "MCP authentication configuration is invalid."


def test_create_mcp_server_requires_server_url(client: TestClient) -> None:
    payload = mcp_server_payload()
    del payload["server_url"]

    response = client.post("/api/v1/mcp-servers", json=payload)

    assert response.status_code == 422


@pytest.mark.parametrize(
    "server_url",
    [
        "mcp.example.com/server",
        "ftp://mcp.example.com/server",
        "not a url",
        "https://user:password@mcp.example.com/server",
    ],
)
def test_create_mcp_server_rejects_malformed_or_credentialed_urls(
    client: TestClient,
    server_url: str,
) -> None:
    payload = mcp_server_payload()
    payload["server_url"] = server_url

    response = client.post("/api/v1/mcp-servers", json=payload)

    assert response.status_code == 422


def test_development_allows_private_mcp_url(client: TestClient) -> None:
    payload = mcp_server_payload()
    payload["server_url"] = "http://127.0.0.1:9000/mcp"

    response = client.post("/api/v1/mcp-servers", json=payload)

    assert response.status_code == 201


def test_production_rejects_private_mcp_url(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ENVIRONMENT", "production")
    monkeypatch.setenv("JWT_SECRET_KEY", "A-strong-production-secret-with-32-characters!")
    monkeypatch.setenv("ALLOW_PRIVATE_MCP_URLS", "false")
    get_settings.cache_clear()
    try:
        with pytest.raises(
            ValidationError,
            match="Private network MCP server URLs are not allowed",
        ):
            MCPServerCreate.model_validate(
                {
                    "name": "Private MCP",
                    "server_url": "http://127.0.0.1:9000/mcp",
                }
            )
    finally:
        get_settings.cache_clear()


def test_update_mcp_server_rejects_url_with_credentials(client: TestClient) -> None:
    mcp_server = create_mcp_server(client)

    response = client.patch(
        f"/api/v1/mcp-servers/{mcp_server['id']}",
        json={"server_url": "https://user:password@mcp.example.com/server"},
    )

    assert response.status_code == 422


def test_list_mcp_servers(client: TestClient) -> None:
    create_mcp_server(client, "Knowledge MCP")
    create_mcp_server(client, "Operations MCP")

    response = client.get("/api/v1/mcp-servers")

    assert response.status_code == 200
    assert response.json()["total"] == 2
    assert {item["name"] for item in response.json()["items"]} == {
        "Knowledge MCP",
        "Operations MCP",
    }


def test_get_mcp_server_by_id(client: TestClient) -> None:
    mcp_server = create_mcp_server(client)

    response = client.get(f"/api/v1/mcp-servers/{mcp_server['id']}")

    assert response.status_code == 200
    assert response.json()["id"] == mcp_server["id"]


def test_update_mcp_server(client: TestClient) -> None:
    mcp_server = create_mcp_server(client)

    response = client.patch(
        f"/api/v1/mcp-servers/{mcp_server['id']}",
        json={
            "name": "Connected Knowledge MCP",
            "status": "connected",
            "last_sync_at": "2026-06-07T08:00:00Z",
        },
    )

    assert response.status_code == 200
    assert response.json()["name"] == "Connected Knowledge MCP"
    assert response.json()["status"] == "connected"
    assert response.json()["last_sync_at"].startswith("2026-06-07T08:00:00")


def test_soft_delete_mcp_server(client: TestClient) -> None:
    mcp_server = create_mcp_server(client)

    response = client.delete(f"/api/v1/mcp-servers/{mcp_server['id']}")

    assert response.status_code == 204
    assert client.get(f"/api/v1/mcp-servers/{mcp_server['id']}").status_code == 404


def test_soft_deleted_mcp_server_excluded_from_list(client: TestClient) -> None:
    deleted_server = create_mcp_server(client, "Deleted MCP")
    visible_server = create_mcp_server(client, "Visible MCP")
    client.delete(f"/api/v1/mcp-servers/{deleted_server['id']}")

    response = client.get("/api/v1/mcp-servers")

    assert response.json()["total"] == 1
    assert response.json()["items"][0]["id"] == visible_server["id"]


def test_duplicate_non_deleted_name_returns_409(client: TestClient) -> None:
    create_mcp_server(client)

    response = client.post("/api/v1/mcp-servers", json=mcp_server_payload())

    assert response.status_code == 409


def test_same_name_can_be_reused_after_soft_delete(client: TestClient) -> None:
    mcp_server = create_mcp_server(client)
    client.delete(f"/api/v1/mcp-servers/{mcp_server['id']}")

    response = client.post("/api/v1/mcp-servers", json=mcp_server_payload())

    assert response.status_code == 201


def test_audit_log_created_after_mcp_server_create(client: TestClient) -> None:
    mcp_server = create_mcp_server(client)

    logs = audit_logs(client, "mcp_server.created")

    assert len(logs) == 1
    assert logs[0]["entity_type"] == "mcp_server"
    assert logs[0]["entity_id"] == mcp_server["id"]
    assert logs[0]["before"] is None
    assert logs[0]["after"]["name"] == "Knowledge MCP"


def test_mcp_auth_secret_value_is_not_stored_in_audit_logs(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("MCP_AUTH_CUSTOMER_OPERATIONS", "super-sensitive-token")
    payload = mcp_server_payload()
    payload.update(
        {
            "auth_type": "bearer",
            "auth_secret_ref": "MCP_AUTH_CUSTOMER_OPERATIONS",
        }
    )

    response = client.post("/api/v1/mcp-servers", json=payload)
    logs = audit_logs(client, "mcp_server.created")

    assert response.status_code == 201
    assert "super-sensitive-token" not in str(logs)
    assert logs[0]["after"]["auth_secret_ref"] == "MCP_AUTH_CUSTOMER_OPERATIONS"


def test_audit_log_created_after_mcp_server_update(client: TestClient) -> None:
    mcp_server = create_mcp_server(client)
    client.patch(f"/api/v1/mcp-servers/{mcp_server['id']}", json={"status": "error"})

    logs = audit_logs(client, "mcp_server.updated")

    assert len(logs) == 1
    assert logs[0]["before"]["status"] == "disconnected"
    assert logs[0]["after"]["status"] == "error"


def test_audit_log_created_after_mcp_server_delete(client: TestClient) -> None:
    mcp_server = create_mcp_server(client)
    client.delete(f"/api/v1/mcp-servers/{mcp_server['id']}")

    logs = audit_logs(client, "mcp_server.deleted")

    assert len(logs) == 1
    assert logs[0]["before"]["deleted_at"] is None
    assert logs[0]["after"]["deleted_at"] is not None


def test_sync_creates_linked_agent_when_missing(client: TestClient) -> None:
    mcp_server = create_mcp_server(client)

    result = sync_mcp_server(client, str(mcp_server["id"]))

    server_response = client.get(f"/api/v1/mcp-servers/{mcp_server['id']}")
    agent_response = client.get(f"/api/v1/agents/{result['agent_id']}")
    assert server_response.json()["agent_id"] == result["agent_id"]
    assert agent_response.status_code == 200
    assert agent_response.json()["name"] == "Knowledge MCP"


def test_sync_reuses_linked_agent_when_present(client: TestClient) -> None:
    agent_response = client.post(
        "/api/v1/agents",
        json={
            "name": "Existing MCP Agent",
            "owner": "platform",
            "department": "governance",
            "risk_level": "medium",
        },
    )
    assert agent_response.status_code == 201
    payload = mcp_server_payload()
    payload["agent_id"] = agent_response.json()["id"]
    server_response = client.post("/api/v1/mcp-servers", json=payload)
    assert server_response.status_code == 201

    result = sync_mcp_server(client, server_response.json()["id"])

    assert result["agent_id"] == agent_response.json()["id"]
    assert client.get("/api/v1/agents").json()["total"] == 1


def test_sync_creates_discovered_tools(client: TestClient) -> None:
    mcp_server = create_mcp_server(client)

    result = sync_mcp_server(client, str(mcp_server["id"]))
    tools = client.get(f"/api/v1/agents/{result['agent_id']}/tools").json()

    assert result["discovered_tools_count"] == 3
    assert result["created_tools_count"] == 3
    assert tools["total"] == 3
    assert {tool["name"] for tool in tools["items"]} == {
        "list_customers",
        "create_ticket",
        "summarize_policy",
    }
    assert all(tool["permission"] == "execute" for tool in tools["items"])
    assert all(tool["risk_level"] == "medium" for tool in tools["items"])
    assert all(tool["is_enabled"] is True for tool in tools["items"])


def test_repeated_sync_does_not_duplicate_tools(client: TestClient) -> None:
    mcp_server = create_mcp_server(client)
    first_result = sync_mcp_server(client, str(mcp_server["id"]))

    second_result = sync_mcp_server(client, str(mcp_server["id"]))
    tools = client.get(f"/api/v1/agents/{first_result['agent_id']}/tools").json()

    assert second_result["created_tools_count"] == 0
    assert second_result["updated_tools_count"] == 3
    assert tools["total"] == 3


def test_repeated_sync_updates_descriptions(client: TestClient) -> None:
    mcp_server = create_mcp_server(client)
    result = sync_mcp_server(client, str(mcp_server["id"]))
    client.patch(
        f"/api/v1/mcp-servers/{mcp_server['id']}",
        json={"server_url": "https://updated.example.com/mcp"},
    )

    sync_mcp_server(client, str(mcp_server["id"]))
    tools = client.get(f"/api/v1/agents/{result['agent_id']}/tools").json()["items"]

    assert all(tool["description"].startswith("Updated ") for tool in tools)


def test_sync_preserves_existing_risk_level_and_permission(client: TestClient) -> None:
    mcp_server = create_mcp_server(client)
    result = sync_mcp_server(client, str(mcp_server["id"]))
    tools = client.get(f"/api/v1/agents/{result['agent_id']}/tools").json()["items"]
    tool = next(item for item in tools if item["name"] == "list_customers")
    client.patch(
        f"/api/v1/agents/{result['agent_id']}/tools/{tool['id']}",
        json={"permission": "read", "risk_level": "critical"},
    )

    sync_mcp_server(client, str(mcp_server["id"]))
    updated_tool = client.get(f"/api/v1/agents/{result['agent_id']}/tools/{tool['id']}").json()

    assert updated_tool["permission"] == "read"
    assert updated_tool["risk_level"] == "critical"


def test_sync_sets_status_connected_and_last_sync_at(client: TestClient) -> None:
    mcp_server = create_mcp_server(client)

    result = sync_mcp_server(client, str(mcp_server["id"]))
    server = client.get(f"/api/v1/mcp-servers/{mcp_server['id']}").json()

    assert result["status"] == "connected"
    assert result["last_sync_at"] is not None
    assert server["status"] == "connected"
    assert server["last_sync_at"] is not None


def test_sync_failure_sets_status_error_and_last_error(client: TestClient) -> None:
    payload = mcp_server_payload()
    payload["server_url"] = "https://fail.example.com/mcp"
    response = client.post("/api/v1/mcp-servers", json=payload)
    assert response.status_code == 201

    sync_response = client.post(f"/api/v1/mcp-servers/{response.json()['id']}/sync")
    server = client.get(f"/api/v1/mcp-servers/{response.json()['id']}").json()

    assert sync_response.status_code == 502
    assert sync_response.json()["detail"] == (
        "MCP discovery failed. Check server connectivity and configuration."
    )
    assert server["status"] == "error"
    assert server["last_error"] == (
        "MCP discovery failed. Check server connectivity and configuration."
    )


def test_sync_failure_preserves_existing_agent_tools_and_last_sync(client: TestClient) -> None:
    mcp_server = create_mcp_server(client)
    first_sync = sync_mcp_server(client, str(mcp_server["id"]))
    before_server = client.get(f"/api/v1/mcp-servers/{mcp_server['id']}").json()
    before_tools = client.get(f"/api/v1/agents/{first_sync['agent_id']}/tools").json()
    client.patch(
        f"/api/v1/mcp-servers/{mcp_server['id']}",
        json={"server_url": "https://fail.example.com/mcp"},
    )

    response = client.post(f"/api/v1/mcp-servers/{mcp_server['id']}/sync")

    after_server = client.get(f"/api/v1/mcp-servers/{mcp_server['id']}").json()
    after_tools = client.get(f"/api/v1/agents/{first_sync['agent_id']}/tools").json()
    assert response.status_code == 502
    assert after_server["agent_id"] == before_server["agent_id"]
    assert after_server["last_sync_at"] == before_server["last_sync_at"]
    assert after_server["status"] == "error"
    assert after_server["last_error"] == (
        "MCP discovery failed. Check server connectivity and configuration."
    )
    assert after_tools == before_tools


def test_sync_success_clears_last_error(client: TestClient) -> None:
    payload = mcp_server_payload()
    payload["server_url"] = "https://fail.example.com/mcp"
    response = client.post("/api/v1/mcp-servers", json=payload)
    server_id = response.json()["id"]
    client.post(f"/api/v1/mcp-servers/{server_id}/sync")
    client.patch(
        f"/api/v1/mcp-servers/{server_id}",
        json={"server_url": "https://mcp.example.com/server"},
    )

    sync_mcp_server(client, server_id)
    server = client.get(f"/api/v1/mcp-servers/{server_id}").json()

    assert server["status"] == "connected"
    assert server["last_error"] is None


def test_audit_log_created_on_sync_success(client: TestClient) -> None:
    mcp_server = create_mcp_server(client)

    sync_mcp_server(client, str(mcp_server["id"]))
    logs = audit_logs(client, "mcp_server.synced")

    assert len(logs) == 1
    assert logs[0]["before"]["status"] == "disconnected"
    assert logs[0]["after"]["status"] == "connected"
    assert logs[0]["after"]["agent_id"] is not None


def test_audit_log_created_on_sync_failure(client: TestClient) -> None:
    payload = mcp_server_payload()
    payload["server_url"] = "https://fail.example.com/mcp"
    response = client.post("/api/v1/mcp-servers", json=payload)

    client.post(f"/api/v1/mcp-servers/{response.json()['id']}/sync")
    logs = audit_logs(client, "mcp_server.sync_failed")

    assert len(logs) == 1
    assert logs[0]["before"]["status"] == "disconnected"
    assert logs[0]["after"]["status"] == "error"
    assert logs[0]["after"]["last_error"] == (
        "MCP discovery failed. Check server connectivity and configuration."
    )


def test_sync_failure_does_not_expose_adapter_details(client: TestClient) -> None:
    class SensitiveFailureAdapter:
        def discover_tools(self, target: object) -> list[object]:
            raise RuntimeError(
                "Connection failed for https://user:password@internal.example/mcp?token=secret"
            )

    mcp_server = create_mcp_server(client, "Safe Failure MCP")
    app = cast(FastAPI, client.app)
    app.dependency_overrides[get_mcp_discovery_adapter] = lambda: SensitiveFailureAdapter()
    try:
        response = client.post(f"/api/v1/mcp-servers/{mcp_server['id']}/sync")
    finally:
        app.dependency_overrides.pop(get_mcp_discovery_adapter, None)
    server = client.get(f"/api/v1/mcp-servers/{mcp_server['id']}").json()

    assert response.status_code == 502
    assert response.json()["detail"] == (
        "MCP discovery failed. Check server connectivity and configuration."
    )
    assert server["last_error"] == response.json()["detail"]
    assert "password" not in str(response.json()).lower()
    assert "internal.example" not in str(server).lower()


def test_invalid_discovered_tool_metadata_uses_safe_failure_path(client: TestClient) -> None:
    class InvalidToolAdapter:
        def discover_tools(self, target: object) -> list[object]:
            return [type("Tool", (), {"name": "x" * 256, "description": "invalid"})()]

    mcp_server = create_mcp_server(client, "Invalid Tool MCP")
    app = cast(FastAPI, client.app)
    app.dependency_overrides[get_mcp_discovery_adapter] = lambda: InvalidToolAdapter()
    try:
        response = client.post(f"/api/v1/mcp-servers/{mcp_server['id']}/sync")
    finally:
        app.dependency_overrides.pop(get_mcp_discovery_adapter, None)

    server = client.get(f"/api/v1/mcp-servers/{mcp_server['id']}").json()
    logs = audit_logs(client, "mcp_server.sync_failed")
    assert response.status_code == 502
    assert response.json()["detail"] == (
        "MCP discovery failed. Check server connectivity and configuration."
    )
    assert server["status"] == "error"
    assert server["agent_id"] is None
    assert server["last_sync_at"] is None
    assert len(logs) == 1
