from typing import Any, cast

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.adapters.mcp_discovery import (
    DiscoveredMCPTool,
    MCPDiscoveryTarget,
    get_mcp_discovery_adapter,
)


class SchemaAdapter:
    def __init__(self, tools: list[DiscoveredMCPTool]) -> None:
        self.tools = tools

    def discover_tools(self, target: MCPDiscoveryTarget) -> list[DiscoveredMCPTool]:
        return self.tools


def create_and_sync(
    client: TestClient,
    tools: list[DiscoveredMCPTool],
    *,
    name: str = "Schema MCP",
) -> tuple[dict[str, Any], dict[str, Any]]:
    response = client.post(
        "/api/v1/mcp-servers",
        json={"name": name, "server_url": "https://schema.example.com/mcp"},
    )
    assert response.status_code == 201
    server = response.json()
    app = cast(FastAPI, client.app)
    app.dependency_overrides[get_mcp_discovery_adapter] = lambda: SchemaAdapter(tools)
    sync_response = client.post(f"/api/v1/mcp-servers/{server['id']}/sync")
    assert sync_response.status_code == 200
    return server, sync_response.json()


def schema_tool(description: str = "Lookup a customer.") -> DiscoveredMCPTool:
    return DiscoveredMCPTool(
        name="lookup_customer",
        description=description,
        input_schema={"type": "object", "properties": {"customer_id": {"type": "string"}}},
        output_schema={"type": "object", "properties": {"name": {"type": "string"}}},
    )


def test_sync_persists_schemas_and_new_tool_is_unreviewed(client: TestClient) -> None:
    create_and_sync(client, [schema_tool()])

    response = client.get("/api/v1/tool-governance")

    assert response.status_code == 200
    tool = response.json()["items"][0]
    assert tool["input_schema"]["properties"]["customer_id"]["type"] == "string"
    assert tool["output_schema"]["properties"]["name"]["type"] == "string"
    assert tool["schema_hash"]
    assert tool["schema_version"] == 1
    assert tool["governance_status"] == "unreviewed"


def test_sync_detects_schema_description_and_removed_tool_changes(client: TestClient) -> None:
    server, _ = create_and_sync(
        client,
        [schema_tool(), DiscoveredMCPTool(name="removed_tool", description="Temporary.")],
    )
    changed = schema_tool("Updated customer lookup.")
    changed = DiscoveredMCPTool(
        name=changed.name,
        description=changed.description,
        input_schema={"type": "object", "required": ["customer_id"]},
        output_schema=changed.output_schema,
    )
    app = cast(FastAPI, client.app)
    app.dependency_overrides[get_mcp_discovery_adapter] = lambda: SchemaAdapter([changed])

    response = client.post(f"/api/v1/mcp-servers/{server['id']}/sync")
    logs = client.get("/api/v1/audit-logs").json()["items"]

    assert response.status_code == 200
    tool = client.get("/api/v1/tool-governance").json()["items"][0]
    assert tool["schema_version"] == 2
    assert tool["description"] == "Updated customer lookup."
    actions = {log["action"] for log in logs}
    assert "mcp_tool.schema_changed" in actions
    assert "mcp_tool.description_changed" in actions
    assert "mcp_tool.removed" in actions
    assert client.get("/api/v1/tool-governance-summary").json()["schema_changes_this_month"] == 1
    assert client.get("/api/v1/dashboard/summary").json()["schema_changes_this_month"] == 1


def test_review_and_policy_coverage_make_tool_governed(client: TestClient) -> None:
    _, sync = create_and_sync(client, [schema_tool()])
    tool = client.get("/api/v1/tool-governance").json()["items"][0]
    policy = client.post(
        "/api/v1/policy-rules",
        json={
            "name": "Govern discovered tools",
            "scope": "global",
            "risk_level": "medium",
            "effect": "require_approval",
            "priority": 10,
        },
    )
    assert policy.status_code == 201

    response = client.post(
        f"/api/v1/tool-governance/{tool['id']}/review",
        json={"risk_level": "high", "permission": "execute"},
    )

    assert sync["agent_id"] == tool["agent_id"]
    assert response.status_code == 200
    reviewed = response.json()
    assert reviewed["governance_status"] == "governed"
    assert reviewed["policy_count"] == 1
    assert reviewed["policy_names"] == ["Govern discovered tools"]
    assert reviewed["reviewed_at"] is not None
    actions = {
        log["action"] for log in client.get("/api/v1/audit-logs").json()["items"]
    }
    assert "mcp_tool.reviewed" in actions
    assert "mcp_tool.risk_changed" in actions
    assert client.get("/api/v1/dashboard/summary").json()["governed_tools"] == 1


def test_tool_governance_summary_and_dashboard_metrics(client: TestClient) -> None:
    create_and_sync(client, [schema_tool()])

    report = client.get("/api/v1/tool-governance-summary")
    dashboard = client.get("/api/v1/dashboard/summary")

    assert report.status_code == 200
    assert report.json()["total_tools"] == 1
    assert report.json()["unreviewed_tools"] == 1
    assert report.json()["review_coverage"] == 0.0
    assert dashboard.status_code == 200
    assert dashboard.json()["discovered_tools"] == 1
    assert dashboard.json()["unreviewed_tools"] == 1
