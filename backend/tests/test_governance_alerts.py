from typing import Any, cast

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.adapters.mcp_discovery import (
    DiscoveredMCPTool,
    MCPDiscoveryTarget,
    get_mcp_discovery_adapter,
)


class AlertDiscoveryAdapter:
    def __init__(self, tools: list[DiscoveredMCPTool]) -> None:
        self.tools = tools

    def discover_tools(self, target: MCPDiscoveryTarget) -> list[DiscoveredMCPTool]:
        return self.tools


def tool(description: str = "Search records.", schema_type: str = "string") -> DiscoveredMCPTool:
    return DiscoveredMCPTool(
        name="search_records",
        description=description,
        input_schema={"type": "object", "properties": {"query": {"type": schema_type}}},
    )


def create_server(client: TestClient) -> dict[str, Any]:
    response = client.post(
        "/api/v1/mcp-servers",
        json={"name": "Alert MCP", "server_url": "https://alerts.example.com/mcp"},
    )
    assert response.status_code == 201
    return cast(dict[str, Any], response.json())


def sync(client: TestClient, server_id: str, tools: list[DiscoveredMCPTool]) -> None:
    app = cast(FastAPI, client.app)
    app.dependency_overrides[get_mcp_discovery_adapter] = lambda: AlertDiscoveryAdapter(tools)
    response = client.post(f"/api/v1/mcp-servers/{server_id}/sync")
    assert response.status_code == 200


def alerts(client: TestClient, **params: str) -> list[dict[str, Any]]:
    response = client.get("/api/v1/governance-alerts", params=params)
    assert response.status_code == 200
    return cast(list[dict[str, Any]], response.json()["items"])


def test_sync_generates_idempotent_new_tool_and_governance_gap_alerts(
    client: TestClient,
) -> None:
    server = create_server(client)

    sync(client, server["id"], [tool()])
    sync(client, server["id"], [tool()])
    current = alerts(client)

    assert sum(item["alert_type"] == "new_tool_discovered" for item in current) == 1
    assert sum(item["alert_type"] == "ungoverned_tool" for item in current) == 1


def test_schema_description_and_removed_tool_alerts(client: TestClient) -> None:
    server = create_server(client)
    sync(client, server["id"], [tool(), DiscoveredMCPTool(name="removed_tool")])

    sync(client, server["id"], [tool("Updated description.", "number")])
    types = {item["alert_type"] for item in alerts(client)}

    assert "schema_changed" in types
    assert "description_changed" in types
    assert "tool_removed" in types


def test_alert_acknowledge_resolve_and_reopen_workflow(client: TestClient) -> None:
    server = create_server(client)
    sync(client, server["id"], [tool()])
    alert = alerts(client, alert_type="new_tool_discovered")[0]

    acknowledged = client.post(f"/api/v1/governance-alerts/{alert['id']}/acknowledge")
    resolved = client.post(f"/api/v1/governance-alerts/{alert['id']}/resolve")
    reopened = client.post(f"/api/v1/governance-alerts/{alert['id']}/reopen")

    assert acknowledged.status_code == 200
    assert acknowledged.json()["status"] == "acknowledged"
    assert acknowledged.json()["acknowledged_by_user_id"] is not None
    assert resolved.status_code == 200
    assert resolved.json()["status"] == "resolved"
    assert reopened.status_code == 200
    assert reopened.json()["status"] == "open"
    actions = {item["action"] for item in client.get("/api/v1/audit-logs").json()["items"]}
    assert "governance_alert.acknowledged" in actions
    assert "governance_alert.resolved" in actions
    assert "governance_alert.reopened" in actions


def test_policy_coverage_loss_alert_and_health_score(client: TestClient) -> None:
    server = create_server(client)
    sync(client, server["id"], [tool()])
    governance_tool = client.get("/api/v1/tool-governance").json()["items"][0]
    policy = client.post(
        "/api/v1/policy-rules",
        json={
            "name": "Cover all MCP tools",
            "scope": "global",
            "risk_level": "medium",
            "effect": "require_approval",
        },
    )
    assert policy.status_code == 201
    review = client.post(
        f"/api/v1/tool-governance/{governance_tool['id']}/review",
        json={"risk_level": "high", "permission": "execute"},
    )
    assert review.status_code == 200
    assert review.json()["governance_status"] == "governed"

    deleted = client.delete(f"/api/v1/policy-rules/{policy.json()['id']}")
    health = client.get("/api/v1/governance-health")

    assert deleted.status_code == 204
    assert alerts(client, alert_type="policy_coverage_lost")
    assert health.status_code == 200
    assert health.json()["score"] < 100
    assert health.json()["governance_gaps"] >= 1


def test_dashboard_includes_alert_metrics(client: TestClient) -> None:
    server = create_server(client)
    sync(client, server["id"], [tool()])

    summary = client.get("/api/v1/dashboard/summary").json()

    assert summary["governance_health"] < 100
    assert summary["open_governance_alerts"] >= 2
    assert summary["governance_gaps"] >= 1
