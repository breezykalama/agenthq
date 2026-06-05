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


def create_tool(
    client: TestClient,
    agent_id: str,
    name: str = "document_search",
    is_enabled: bool = True,
) -> JsonResponse:
    response = client.post(
        f"/api/v1/agents/{agent_id}/tools",
        json={
            "name": name,
            "description": "Search internal policy documents.",
            "permission": "read",
            "risk_level": "low",
            "is_enabled": is_enabled,
        },
    )
    assert response.status_code == 201
    return cast(JsonResponse, response.json())


def create_policy_rule(
    client: TestClient,
    name: str,
    effect: str,
    risk_level: str = "low",
    scope: str = "global",
    agent_id: str | None = None,
    tool_id: str | None = None,
    priority: int = 100,
    is_enabled: bool = True,
) -> JsonResponse:
    payload: dict[str, object] = {
        "name": name,
        "description": "Decision test policy.",
        "scope": scope,
        "risk_level": risk_level,
        "effect": effect,
        "is_enabled": is_enabled,
        "priority": priority,
    }
    if agent_id is not None:
        payload["agent_id"] = agent_id
    if tool_id is not None:
        payload["tool_id"] = tool_id

    response = client.post("/api/v1/policy-rules", json=payload)
    assert response.status_code == 201
    return cast(JsonResponse, response.json())


def evaluate(
    client: TestClient,
    agent_id: str,
    risk_level: str,
    tool_id: str | None = None,
) -> JsonResponse:
    payload: dict[str, object] = {
        "agent_id": agent_id,
        "requested_action": "run_tool",
        "risk_level": risk_level,
    }
    if tool_id is not None:
        payload["tool_id"] = tool_id

    response = client.post("/api/v1/policy-decisions/evaluate", json=payload)
    assert response.status_code == 200
    return cast(JsonResponse, response.json())


def audit_logs(client: TestClient) -> list[JsonResponse]:
    response = client.get("/api/v1/audit-logs", params={"action": "policy_decision.evaluated"})
    assert response.status_code == 200
    data = cast(JsonResponse, response.json())
    return cast(list[JsonResponse], data["items"])


def test_default_low_risk_decision_allows(client: TestClient) -> None:
    agent = create_agent(client)

    decision = evaluate(client, str(agent["id"]), "low")

    assert decision["decision"] == "allow"
    assert decision["requires_approval"] is False
    assert decision["matched_rule_id"] is None


def test_default_medium_risk_decision_allows(client: TestClient) -> None:
    agent = create_agent(client)

    decision = evaluate(client, str(agent["id"]), "medium")

    assert decision["decision"] == "allow"


def test_default_high_risk_decision_requires_approval(client: TestClient) -> None:
    agent = create_agent(client)

    decision = evaluate(client, str(agent["id"]), "high")

    assert decision["decision"] == "require_approval"
    assert decision["requires_approval"] is True


def test_default_critical_risk_decision_requires_approval(client: TestClient) -> None:
    agent = create_agent(client)

    decision = evaluate(client, str(agent["id"]), "critical")

    assert decision["decision"] == "require_approval"


def test_global_block_rule_applies(client: TestClient) -> None:
    agent = create_agent(client)
    rule = create_policy_rule(client, "Global block", "block", risk_level="medium")

    decision = evaluate(client, str(agent["id"]), "high")

    assert decision["decision"] == "block"
    assert decision["matched_rule_id"] == rule["id"]


def test_agent_scoped_rule_overrides_global_rule(client: TestClient) -> None:
    agent = create_agent(client)
    create_policy_rule(client, "Global block", "block", risk_level="low", priority=1)
    agent_rule = create_policy_rule(
        client,
        "Agent allow",
        "allow",
        risk_level="low",
        scope="agent",
        agent_id=str(agent["id"]),
        priority=100,
    )

    decision = evaluate(client, str(agent["id"]), "high")

    assert decision["decision"] == "allow"
    assert decision["matched_rule_id"] == agent_rule["id"]


def test_tool_scoped_rule_overrides_agent_and_global_rule(client: TestClient) -> None:
    agent = create_agent(client)
    tool = create_tool(client, str(agent["id"]))
    create_policy_rule(client, "Global block", "block", risk_level="low", priority=1)
    create_policy_rule(
        client,
        "Agent approval",
        "require_approval",
        risk_level="low",
        scope="agent",
        agent_id=str(agent["id"]),
        priority=1,
    )
    tool_rule = create_policy_rule(
        client,
        "Tool allow",
        "allow",
        risk_level="low",
        scope="tool",
        agent_id=str(agent["id"]),
        tool_id=str(tool["id"]),
        priority=100,
    )

    decision = evaluate(client, str(agent["id"]), "high", tool_id=str(tool["id"]))

    assert decision["decision"] == "allow"
    assert decision["matched_rule_id"] == tool_rule["id"]


def test_disabled_rule_ignored(client: TestClient) -> None:
    agent = create_agent(client)
    create_policy_rule(client, "Disabled block", "block", is_enabled=False)

    decision = evaluate(client, str(agent["id"]), "low")

    assert decision["decision"] == "allow"
    assert decision["matched_rule_id"] is None


def test_soft_deleted_rule_ignored(client: TestClient) -> None:
    agent = create_agent(client)
    rule = create_policy_rule(client, "Deleted block", "block")
    client.delete(f"/api/v1/policy-rules/{rule['id']}")

    decision = evaluate(client, str(agent["id"]), "low")

    assert decision["decision"] == "allow"
    assert decision["matched_rule_id"] is None


def test_lowest_priority_number_wins(client: TestClient) -> None:
    agent = create_agent(client)
    create_policy_rule(client, "Later allow", "allow", risk_level="low", priority=50)
    winning_rule = create_policy_rule(
        client,
        "Earlier block",
        "block",
        risk_level="low",
        priority=10,
    )

    decision = evaluate(client, str(agent["id"]), "high")

    assert decision["decision"] == "block"
    assert decision["matched_rule_id"] == winning_rule["id"]


def test_tied_priority_chooses_highest_risk_severity(client: TestClient) -> None:
    agent = create_agent(client)
    create_policy_rule(client, "Low block", "block", risk_level="low", priority=10)
    winning_rule = create_policy_rule(
        client,
        "High approval",
        "require_approval",
        risk_level="high",
        priority=10,
    )

    decision = evaluate(client, str(agent["id"]), "critical")

    assert decision["decision"] == "require_approval"
    assert decision["matched_rule_id"] == winning_rule["id"]


def test_tool_must_belong_to_agent(client: TestClient) -> None:
    first_agent = create_agent(client, "Policy Review Agent")
    second_agent = create_agent(client, "Procurement Triage Agent")
    tool = create_tool(client, str(first_agent["id"]))

    response = client.post(
        "/api/v1/policy-decisions/evaluate",
        json={
            "agent_id": second_agent["id"],
            "tool_id": tool["id"],
            "requested_action": "run_tool",
            "risk_level": "low",
        },
    )

    assert response.status_code == 404


def test_disabled_tool_rejected(client: TestClient) -> None:
    agent = create_agent(client)
    tool = create_tool(client, str(agent["id"]), is_enabled=False)

    response = client.post(
        "/api/v1/policy-decisions/evaluate",
        json={
            "agent_id": agent["id"],
            "tool_id": tool["id"],
            "requested_action": "run_tool",
            "risk_level": "low",
        },
    )

    assert response.status_code == 409


def test_audit_log_created_after_decision_evaluation(client: TestClient) -> None:
    agent = create_agent(client)
    decision = evaluate(client, str(agent["id"]), "high")

    logs = audit_logs(client)

    assert len(logs) == 1
    assert logs[0]["entity_type"] == "policy_decision"
    assert logs[0]["before"] is None
    assert logs[0]["after"]["request"]["agent_id"] == agent["id"]
    assert logs[0]["after"]["response"]["decision"] == decision["decision"]
