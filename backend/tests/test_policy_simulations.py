from typing import Any, cast

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.adapters.mcp_discovery import (
    DiscoveredMCPTool,
    MCPDiscoveryTarget,
    get_mcp_discovery_adapter,
)


class SimulationAdapter:
    def __init__(self, tools: list[DiscoveredMCPTool]) -> None:
        self.tools = tools

    def discover_tools(self, target: MCPDiscoveryTarget) -> list[DiscoveredMCPTool]:
        return self.tools


def sync_server(client: TestClient, name: str, tool_name: str) -> dict[str, Any]:
    server_slug = name.lower().replace(" ", "-")
    server = client.post(
        "/api/v1/mcp-servers",
        json={"name": name, "server_url": f"https://{server_slug}.example.com/mcp"},
    )
    assert server.status_code == 201
    app = cast(FastAPI, client.app)
    app.dependency_overrides[get_mcp_discovery_adapter] = lambda: SimulationAdapter(
        [DiscoveredMCPTool(name=tool_name, description="Simulation tool.")]
    )
    synced = client.post(f"/api/v1/mcp-servers/{server.json()['id']}/sync")
    assert synced.status_code == 200
    return cast(dict[str, Any], synced.json())


def simulation_payload(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "name": "Proposed global approval policy",
        "scope": "global",
        "risk_level": "medium",
        "effect": "require_approval",
        "is_enabled": True,
        "priority": 50,
    }
    payload.update(overrides)
    return payload


def test_policy_simulation_analyzes_tools_agents_and_mcp_servers(client: TestClient) -> None:
    sync_server(client, "Finance MCP", "pay_invoice")
    sync_server(client, "Support MCP", "create_ticket")

    response = client.post("/api/v1/policy-simulations", json=simulation_payload())

    assert response.status_code == 200
    impact = response.json()
    assert impact["affected_tools"]["count"] == 2
    assert impact["affected_agents"]["count"] == 2
    assert impact["affected_mcp_servers"]["count"] == 2
    assert impact["governance_changes"]["becoming_approval_required"]["count"] == 2


def test_policy_simulation_projects_governance_gap_and_alert_resolution(
    client: TestClient,
) -> None:
    sync_server(client, "Review MCP", "review_record")
    tool = client.get("/api/v1/tool-governance").json()["items"][0]
    client.post(
        f"/api/v1/tool-governance/{tool['id']}/review",
        json={"risk_level": "medium", "permission": "execute"},
    )

    response = client.post("/api/v1/policy-simulations", json=simulation_payload())

    impact = response.json()
    assert response.status_code == 200
    assert impact["current_coverage"]["governed_tools"] == 0
    assert impact["projected_coverage"]["governed_tools"] == 1
    assert impact["governance_gaps_resolved"] == 1
    assert impact["alert_impact"]["potentially_resolved_ungoverned_tool"] == 1


def test_policy_simulation_detects_conflicts_and_overlaps(client: TestClient) -> None:
    sync_server(client, "Conflict MCP", "conflicting_tool")
    existing = client.post(
        "/api/v1/policy-rules",
        json={
            "name": "Allow discovered tools",
            "scope": "global",
            "risk_level": "low",
            "effect": "allow",
        },
    )
    assert existing.status_code == 201

    response = client.post(
        "/api/v1/policy-simulations",
        json=simulation_payload(effect="block", risk_level="low"),
    )

    impact = response.json()
    assert response.status_code == 200
    assert impact["warning_count"] == 1
    assert impact["warnings"][0]["conflicting_effects"] is True
    assert impact["alert_impact"]["potentially_created_conflicts"] == 1


def test_policy_simulation_respects_existing_higher_precedence_rule(
    client: TestClient,
) -> None:
    sync_server(client, "Precedence MCP", "protected_tool")
    tool = client.get("/api/v1/tool-governance").json()["items"][0]
    existing = client.post(
        "/api/v1/policy-rules",
        json={
            "name": "Block protected tool",
            "scope": "tool",
            "agent_id": tool["agent_id"],
            "tool_id": tool["id"],
            "risk_level": "low",
            "effect": "block",
            "priority": 100,
        },
    )
    assert existing.status_code == 201

    response = client.post(
        "/api/v1/policy-simulations",
        json=simulation_payload(effect="allow", risk_level="low", priority=1),
    )

    impact = response.json()
    assert response.status_code == 200
    assert impact["affected_tools"]["count"] == 1
    assert impact["governance_changes"]["becoming_explicitly_allowed"]["count"] == 0


def test_policy_simulation_projects_policy_disable_without_persisting(
    client: TestClient,
) -> None:
    sync_server(client, "Disable Preview MCP", "covered_tool")
    tool = client.get("/api/v1/tool-governance").json()["items"][0]
    client.post(
        f"/api/v1/tool-governance/{tool['id']}/review",
        json={"risk_level": "medium", "permission": "execute"},
    )
    policy = client.post(
        "/api/v1/policy-rules",
        json={
            "name": "Current coverage",
            "scope": "global",
            "risk_level": "low",
            "effect": "allow",
        },
    )
    assert policy.status_code == 201

    response = client.post(
        "/api/v1/policy-simulations",
        json=simulation_payload(
            policy_id=policy.json()["id"],
            name="Current coverage",
            risk_level="low",
            effect="allow",
            is_enabled=False,
        ),
    )

    impact = response.json()
    assert response.status_code == 200
    assert impact["current_coverage"]["governed_tools"] == 1
    assert impact["projected_coverage"]["governed_tools"] == 0
    assert client.get("/api/v1/policy-rules").json()["items"][0]["is_enabled"] is True


def test_policy_simulation_has_no_persistence_side_effects(client: TestClient) -> None:
    sync_server(client, "Readonly MCP", "read_only_tool")
    policies_before = client.get("/api/v1/policy-rules").json()["total"]
    alerts_before = client.get("/api/v1/governance-alerts").json()["total"]

    response = client.post("/api/v1/policy-simulations", json=simulation_payload())

    assert response.status_code == 200
    assert client.get("/api/v1/policy-rules").json()["total"] == policies_before
    assert client.get("/api/v1/governance-alerts").json()["total"] == alerts_before


def test_policy_impact_summary_reports_coverage_and_conflicts(client: TestClient) -> None:
    sync_server(client, "Summary MCP", "summary_tool")

    response = client.get("/api/v1/policy-impact-summary")

    assert response.status_code == 200
    assert response.json() == {
        "policy_coverage_percentage": 0.0,
        "governed_tools": 0,
        "ungoverned_tools": 1,
        "governance_gaps": 1,
        "conflict_count": 0,
    }


def test_dashboard_reports_policy_coverage_percentage(client: TestClient) -> None:
    sync_server(client, "Coverage Dashboard MCP", "dashboard_tool")
    tool = client.get("/api/v1/tool-governance").json()["items"][0]
    reviewed = client.post(
        f"/api/v1/tool-governance/{tool['id']}/review",
        json={"risk_level": "medium", "permission": "execute"},
    )
    assert reviewed.status_code == 200
    policy = client.post(
        "/api/v1/policy-rules",
        json={
            "name": "Dashboard coverage",
            "scope": "global",
            "risk_level": "low",
            "effect": "allow",
        },
    )
    assert policy.status_code == 201

    response = client.get("/api/v1/dashboard/summary")

    assert response.status_code == 200
    assert response.json()["policy_coverage_percentage"] == 100.0
