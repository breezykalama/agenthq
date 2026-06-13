from typing import Any, cast

from fastapi.testclient import TestClient


def setup_risk_tools(client: TestClient) -> dict[str, Any]:
    server = client.post(
        "/api/v1/mcp-servers",
        json={"name": "Risk Center MCP", "server_url": "https://risk.example.com/mcp"},
    ).json()
    sync = client.post(f"/api/v1/mcp-servers/{server['id']}/sync")
    assert sync.status_code == 200
    register = client.get("/api/v1/risk-register")
    assert register.status_code == 200
    return {
        "server": server,
        "agent_id": sync.json()["agent_id"],
        "items": cast(list[dict[str, Any]], register.json()["items"]),
    }


def test_risk_register_generates_one_record_per_discovered_tool(client: TestClient) -> None:
    setup = setup_risk_tools(client)
    response = client.get("/api/v1/risk-register")

    assert response.json()["total"] == 3
    assert len({item["tool_id"] for item in response.json()["items"]}) == 3
    assert all(item["compliance_status"] == "non_compliant" for item in setup["items"])


def test_builtin_compliance_controls_are_seeded_idempotently(client: TestClient) -> None:
    setup_risk_tools(client)

    first = client.get("/api/v1/compliance-controls")
    second = client.get("/api/v1/compliance-controls")

    assert [control["name"] for control in first.json()] == [
        "CONTROL_001",
        "CONTROL_002",
        "CONTROL_003",
        "CONTROL_004",
        "CONTROL_005",
    ]
    assert len(second.json()) == 5


def test_compliance_evaluation_reports_violated_controls(client: TestClient) -> None:
    setup_risk_tools(client)

    response = client.get("/api/v1/compliance-evaluation")

    assert response.status_code == 200
    assert response.json()["status"] == "non_compliant"
    assert response.json()["non_compliant_tools"] == 3
    assert {item["control_name"] for item in response.json()["violated_controls"]} == {
        "CONTROL_005"
    }


def test_review_and_policy_make_tool_compliant(client: TestClient) -> None:
    setup = setup_risk_tools(client)
    tool = setup["items"][0]
    review = client.post(
        f"/api/v1/tool-governance/{tool['tool_id']}/review",
        json={"risk_level": "critical", "permission": "execute"},
    )
    assert review.status_code == 200
    client.post(
        "/api/v1/policy-rules",
        json={
            "name": "Critical tools require approval",
            "scope": "global",
            "risk_level": "critical",
            "effect": "require_approval",
        },
    )

    response = client.get("/api/v1/risk-register", params={"risk_level": "critical"})

    assert response.json()["total"] == 1
    assert response.json()["items"][0]["governance_status"] == "governed"
    assert response.json()["items"][0]["compliance_status"] == "compliant"


def test_critical_non_compliance_generates_alerts(client: TestClient) -> None:
    setup = setup_risk_tools(client)
    tool = setup["items"][0]
    client.post(
        f"/api/v1/tool-governance/{tool['tool_id']}/review",
        json={"risk_level": "critical", "permission": "execute"},
    )

    response = client.get("/api/v1/governance-alerts", params={"tool_id": tool["tool_id"]})
    alert_types = {item["alert_type"] for item in response.json()["items"]}

    assert "compliance_non_compliant" in alert_types
    assert "critical_policy_coverage_lost" in alert_types


def test_risk_summary_calculates_score_and_daily_snapshot(client: TestClient) -> None:
    setup_risk_tools(client)

    first = client.get("/api/v1/risk-summary")
    second = client.get("/api/v1/risk-summary")

    assert first.status_code == 200
    assert first.json()["risk_score"] < 100
    assert first.json()["compliance_score"] == 0
    assert len(first.json()["risk_trend"]) == 1
    assert len(second.json()["risk_trend"]) == 1


def test_compliance_evaluation_can_scope_to_tool(client: TestClient) -> None:
    setup = setup_risk_tools(client)

    response = client.get(
        "/api/v1/compliance-evaluation",
        params={"tool_id": setup["items"][0]["tool_id"]},
    )

    assert response.json()["non_compliant_tools"] == 1
    assert response.json()["violated_controls"][0]["failed_tools"] == 1
