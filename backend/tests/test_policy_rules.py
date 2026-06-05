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


def create_tool(client: TestClient, agent_id: str, name: str = "document_search") -> JsonResponse:
    response = client.post(f"/api/v1/agents/{agent_id}/tools", json=tool_payload(name=name))
    assert response.status_code == 201
    return cast(JsonResponse, response.json())


def policy_rule_payload(
    name: str = "Require approval for high risk",
    scope: str = "global",
    agent_id: str | None = None,
    tool_id: str | None = None,
    effect: str = "require_approval",
    risk_level: str = "high",
) -> dict[str, object]:
    payload: dict[str, object] = {
        "name": name,
        "description": "Policy rule for governance tests.",
        "scope": scope,
        "risk_level": risk_level,
        "effect": effect,
        "is_enabled": True,
        "priority": 100,
    }
    if agent_id is not None:
        payload["agent_id"] = agent_id
    if tool_id is not None:
        payload["tool_id"] = tool_id
    return payload


def create_policy_rule(
    client: TestClient,
    name: str = "Require approval for high risk",
    scope: str = "global",
    agent_id: str | None = None,
    tool_id: str | None = None,
    effect: str = "require_approval",
) -> JsonResponse:
    response = client.post(
        "/api/v1/policy-rules",
        json=policy_rule_payload(
            name=name,
            scope=scope,
            agent_id=agent_id,
            tool_id=tool_id,
            effect=effect,
        ),
    )
    assert response.status_code == 201
    return cast(JsonResponse, response.json())


def audit_logs(client: TestClient, action: str) -> list[JsonResponse]:
    response = client.get("/api/v1/audit-logs", params={"action": action})
    assert response.status_code == 200
    data = cast(JsonResponse, response.json())
    return cast(list[JsonResponse], data["items"])


def test_create_global_policy_rule(client: TestClient) -> None:
    rule = create_policy_rule(client)

    assert rule["scope"] == "global"
    assert rule["agent_id"] is None
    assert rule["tool_id"] is None
    assert rule["effect"] == "require_approval"


def test_create_agent_scoped_policy_rule(client: TestClient) -> None:
    agent = create_agent(client)

    rule = create_policy_rule(
        client,
        name="Block high risk for agent",
        scope="agent",
        agent_id=str(agent["id"]),
        effect="block",
    )

    assert rule["scope"] == "agent"
    assert rule["agent_id"] == agent["id"]
    assert rule["tool_id"] is None


def test_create_tool_scoped_policy_rule(client: TestClient) -> None:
    agent = create_agent(client)
    tool = create_tool(client, str(agent["id"]))

    rule = create_policy_rule(
        client,
        name="Allow document search",
        scope="tool",
        agent_id=str(agent["id"]),
        tool_id=str(tool["id"]),
        effect="allow",
    )

    assert rule["scope"] == "tool"
    assert rule["agent_id"] == agent["id"]
    assert rule["tool_id"] == tool["id"]


def test_reject_agent_scope_without_agent_id(client: TestClient) -> None:
    response = client.post(
        "/api/v1/policy-rules",
        json=policy_rule_payload(name="Invalid agent rule", scope="agent"),
    )

    assert response.status_code == 422


def test_reject_tool_scope_without_tool_id(client: TestClient) -> None:
    agent = create_agent(client)

    response = client.post(
        "/api/v1/policy-rules",
        json=policy_rule_payload(
            name="Invalid tool rule",
            scope="tool",
            agent_id=str(agent["id"]),
        ),
    )

    assert response.status_code == 422


def test_reject_tool_scope_where_tool_does_not_belong_to_agent(client: TestClient) -> None:
    first_agent = create_agent(client, "Policy Review Agent")
    second_agent = create_agent(client, "Procurement Triage Agent")
    tool = create_tool(client, str(first_agent["id"]))

    response = client.post(
        "/api/v1/policy-rules",
        json=policy_rule_payload(
            name="Invalid ownership rule",
            scope="tool",
            agent_id=str(second_agent["id"]),
            tool_id=str(tool["id"]),
        ),
    )

    assert response.status_code == 422


def test_reject_duplicate_active_rule_name(client: TestClient) -> None:
    create_policy_rule(client)

    response = client.post("/api/v1/policy-rules", json=policy_rule_payload())

    assert response.status_code == 409


def test_list_policy_rules(client: TestClient) -> None:
    create_policy_rule(client, name="Global approval")
    create_policy_rule(client, name="Global block", effect="block")

    response = client.get("/api/v1/policy-rules")

    assert response.status_code == 200
    data = response.json()
    assert data["total"] == 2
    assert {rule["name"] for rule in data["items"]} == {"Global approval", "Global block"}


def test_filter_policy_rules_by_scope(client: TestClient) -> None:
    agent = create_agent(client)
    agent_rule = create_policy_rule(
        client,
        name="Agent rule",
        scope="agent",
        agent_id=str(agent["id"]),
    )
    create_policy_rule(client, name="Global rule")

    response = client.get("/api/v1/policy-rules", params={"scope": "agent"})

    assert response.status_code == 200
    data = response.json()
    assert data["total"] == 1
    assert data["items"][0]["id"] == agent_rule["id"]


def test_filter_policy_rules_by_effect(client: TestClient) -> None:
    block_rule = create_policy_rule(client, name="Block rule", effect="block")
    create_policy_rule(client, name="Approval rule", effect="require_approval")

    response = client.get("/api/v1/policy-rules", params={"effect": "block"})

    assert response.status_code == 200
    data = response.json()
    assert data["total"] == 1
    assert data["items"][0]["id"] == block_rule["id"]


def test_update_policy_rule(client: TestClient) -> None:
    rule = create_policy_rule(client)

    response = client.patch(
        f"/api/v1/policy-rules/{rule['id']}",
        json={"effect": "block", "priority": 10},
    )

    assert response.status_code == 200
    data = response.json()
    assert data["effect"] == "block"
    assert data["priority"] == 10


def test_disabled_policy_rule_remains_visible(client: TestClient) -> None:
    rule = create_policy_rule(client)

    response = client.patch(f"/api/v1/policy-rules/{rule['id']}", json={"is_enabled": False})
    assert response.status_code == 200

    list_response = client.get("/api/v1/policy-rules")
    data = list_response.json()
    assert data["total"] == 1
    assert data["items"][0]["is_enabled"] is False


def test_soft_delete_policy_rule(client: TestClient) -> None:
    rule = create_policy_rule(client)

    response = client.delete(f"/api/v1/policy-rules/{rule['id']}")

    assert response.status_code == 204


def test_soft_deleted_rule_excluded_from_list(client: TestClient) -> None:
    deleted_rule = create_policy_rule(client, name="Deleted rule")
    visible_rule = create_policy_rule(client, name="Visible rule")
    client.delete(f"/api/v1/policy-rules/{deleted_rule['id']}")

    response = client.get("/api/v1/policy-rules")

    assert response.status_code == 200
    data = response.json()
    assert data["total"] == 1
    assert data["items"][0]["id"] == visible_rule["id"]


def test_audit_log_created_after_policy_rule_create(client: TestClient) -> None:
    rule = create_policy_rule(client)

    logs = audit_logs(client, "policy_rule.created")

    assert len(logs) == 1
    assert logs[0]["entity_type"] == "policy_rule"
    assert logs[0]["entity_id"] == rule["id"]
    assert logs[0]["before"] is None
    assert logs[0]["after"]["name"] == "Require approval for high risk"


def test_audit_log_created_after_policy_rule_update(client: TestClient) -> None:
    rule = create_policy_rule(client)

    client.patch(f"/api/v1/policy-rules/{rule['id']}", json={"name": "Updated rule"})
    logs = audit_logs(client, "policy_rule.updated")

    assert len(logs) == 1
    assert logs[0]["before"]["name"] == "Require approval for high risk"
    assert logs[0]["after"]["name"] == "Updated rule"


def test_audit_log_created_after_policy_rule_delete(client: TestClient) -> None:
    rule = create_policy_rule(client)

    client.delete(f"/api/v1/policy-rules/{rule['id']}")
    logs = audit_logs(client, "policy_rule.deleted")

    assert len(logs) == 1
    assert logs[0]["before"]["deleted_at"] is None
    assert logs[0]["after"]["deleted_at"] is not None
