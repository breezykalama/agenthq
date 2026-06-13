from typing import Any, cast

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.adapters.mcp_discovery import (
    DiscoveredMCPTool,
    MCPDiscoveryTarget,
    get_mcp_discovery_adapter,
)
from app.adapters.mcp_execution import (
    MCPExecutionError,
    MCPToolExecutionResult,
    get_mcp_execution_adapter,
)
from app.core.config import get_settings
from app.core.rate_limit import reset_rate_limit_backend


class DiscoveryAdapter:
    def discover_tools(self, target: MCPDiscoveryTarget) -> list[DiscoveredMCPTool]:
        return [
            DiscoveredMCPTool(
                "transfer_funds",
                "Transfer funds.",
                input_schema={"type": "object"},
            )
        ]


class ExecutionAdapter:
    def __init__(self) -> None:
        self.calls = 0

    def call_tool(
        self,
        target: MCPDiscoveryTarget,
        tool_name: str,
        arguments: dict[str, object],
    ) -> MCPToolExecutionResult:
        self.calls += 1
        return MCPToolExecutionResult(payload={"content": [{"type": "text", "text": "done"}]})


class FailingExecutionAdapter:
    def call_tool(
        self,
        target: MCPDiscoveryTarget,
        tool_name: str,
        arguments: dict[str, object],
    ) -> MCPToolExecutionResult:
        raise MCPExecutionError("secret upstream.internal")


class TimeoutExecutionAdapter:
    def call_tool(
        self,
        target: MCPDiscoveryTarget,
        tool_name: str,
        arguments: dict[str, object],
    ) -> MCPToolExecutionResult:
        raise TimeoutError("private timeout detail")


def setup_gateway(client: TestClient, *, risk_level: str = "medium") -> dict[str, Any]:
    server_response = client.post(
        "/api/v1/mcp-servers",
        json={"name": "Gateway MCP", "server_url": "https://gateway.example.com/mcp"},
    )
    assert server_response.status_code == 201
    server = cast(dict[str, Any], server_response.json())
    app = cast(FastAPI, client.app)
    app.dependency_overrides[get_mcp_discovery_adapter] = lambda: DiscoveryAdapter()
    sync = client.post(f"/api/v1/mcp-servers/{server['id']}/sync")
    assert sync.status_code == 200
    tool = client.get("/api/v1/tool-governance").json()["items"][0]
    review = client.post(
        f"/api/v1/tool-governance/{tool['id']}/review",
        json={"risk_level": risk_level, "permission": "execute"},
    )
    assert review.status_code == 200
    token_response = client.post(
        "/api/v1/mcp-gateway-tokens",
        json={"mcp_server_id": server["id"], "name": "Test gateway client"},
    )
    assert token_response.status_code == 201
    token = cast(dict[str, Any], token_response.json())
    return {"server": server, "tool": tool, "token": token, "app": app}


def gateway_headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def test_gateway_token_returns_raw_once_and_rotation_invalidates_old_token(
    client: TestClient,
) -> None:
    setup = setup_gateway(client)
    token = setup["token"]
    server_id = setup["server"]["id"]

    listed = client.get("/api/v1/mcp-gateway-tokens")
    rotated = client.post(f"/api/v1/mcp-gateway-tokens/{token['id']}/rotate")

    assert listed.status_code == 200
    assert "token" not in listed.json()["items"][0]
    assert "token_hash" not in listed.json()["items"][0]
    assert rotated.status_code == 200
    assert rotated.json()["token"] != token["token"]
    assert (
        client.get(
            f"/api/v1/mcp-gateway/{server_id}/tools",
            headers=gateway_headers(token["token"]),
        ).status_code
        == 401
    )


def test_gateway_rejects_invalid_and_revoked_tokens(client: TestClient) -> None:
    setup = setup_gateway(client)
    token = setup["token"]
    server_id = setup["server"]["id"]
    invalid = client.get(
        f"/api/v1/mcp-gateway/{server_id}/tools",
        headers=gateway_headers("aghq_invalid"),
    )
    client.post(f"/api/v1/mcp-gateway-tokens/{token['id']}/revoke")
    revoked = client.get(
        f"/api/v1/mcp-gateway/{server_id}/tools",
        headers=gateway_headers(token["token"]),
    )

    assert invalid.status_code == 401
    assert revoked.status_code == 401


def test_gateway_lists_only_reviewed_enabled_tools(client: TestClient) -> None:
    server = client.post(
        "/api/v1/mcp-servers",
        json={"name": "Review Gateway", "server_url": "https://review.example.com/mcp"},
    ).json()
    app = cast(FastAPI, client.app)
    app.dependency_overrides[get_mcp_discovery_adapter] = lambda: DiscoveryAdapter()
    client.post(f"/api/v1/mcp-servers/{server['id']}/sync")
    tool = client.get("/api/v1/tool-governance").json()["items"][0]
    token = client.post(
        "/api/v1/mcp-gateway-tokens",
        json={"mcp_server_id": server["id"], "name": "Review token"},
    ).json()["token"]

    hidden = client.get(
        f"/api/v1/mcp-gateway/{server['id']}/tools",
        headers=gateway_headers(token),
    )
    client.post(
        f"/api/v1/tool-governance/{tool['id']}/review",
        json={"risk_level": "medium", "permission": "execute"},
    )
    visible = client.get(
        f"/api/v1/mcp-gateway/{server['id']}/tools",
        headers=gateway_headers(token),
    )

    assert hidden.json()["total"] == 0
    assert visible.json()["total"] == 1
    assert visible.json()["items"][0]["input_schema"] == {"type": "object"}


def test_blocked_gateway_call_does_not_call_upstream(client: TestClient) -> None:
    setup = setup_gateway(client)
    adapter = ExecutionAdapter()
    setup["app"].dependency_overrides[get_mcp_execution_adapter] = lambda: adapter
    client.post(
        "/api/v1/policy-rules",
        json={
            "name": "Block transfer",
            "scope": "tool",
            "agent_id": setup["tool"]["agent_id"],
            "tool_id": setup["tool"]["id"],
            "risk_level": "low",
            "effect": "block",
        },
    )

    response = call_tool(client, setup)

    assert response.status_code == 200
    assert response.json()["status"] == "blocked"
    assert adapter.calls == 0


def test_gateway_requires_approval_without_calling_upstream(client: TestClient) -> None:
    setup = setup_gateway(client, risk_level="high")
    adapter = ExecutionAdapter()
    setup["app"].dependency_overrides[get_mcp_execution_adapter] = lambda: adapter

    response = call_tool(client, setup)

    assert response.status_code == 200
    assert response.json()["status"] == "requires_approval"
    assert adapter.calls == 0


def test_gateway_policy_failure_fails_closed(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    setup = setup_gateway(client)
    adapter = ExecutionAdapter()
    setup["app"].dependency_overrides[get_mcp_execution_adapter] = lambda: adapter

    def fail_policy(*args: object, **kwargs: object) -> None:
        raise RuntimeError("unexpected policy failure")

    monkeypatch.setattr(
        "app.services.policy_decisions.evaluate_policy_decision",
        fail_policy,
    )

    response = call_tool(client, setup)

    assert response.status_code == 200
    assert response.json()["status"] == "blocked"
    assert "fail-closed fallback" in response.json()["policy_decision_reason"]
    assert adapter.calls == 0


def test_approved_gateway_call_calls_upstream_and_creates_execution(client: TestClient) -> None:
    setup = setup_gateway(client, risk_level="high")
    adapter = ExecutionAdapter()
    setup["app"].dependency_overrides[get_mcp_execution_adapter] = lambda: adapter
    approval = client.post(
        "/api/v1/approvals",
        json={
            "agent_id": setup["tool"]["agent_id"],
            "requested_action": "transfer_funds",
            "risk_level": "high",
        },
    ).json()
    client.post(f"/api/v1/approvals/{approval['id']}/approve")

    response = call_tool(client, setup, approval_id=approval["id"])
    execution = client.get(f"/api/v1/executions/{response.json()['execution_id']}")

    assert response.status_code == 200
    assert response.json()["status"] == "succeeded"
    assert response.json()["result"]["content"][0]["text"] == "done"
    assert adapter.calls == 1
    assert execution.json()["status"] == "succeeded"


def test_gateway_failure_is_sanitized_and_recorded(client: TestClient) -> None:
    setup = setup_gateway(client)
    setup["app"].dependency_overrides[get_mcp_execution_adapter] = lambda: FailingExecutionAdapter()

    response = call_tool(client, setup)

    assert response.status_code == 200
    assert response.json()["status"] == "failed"
    assert response.json()["error"] == "Upstream MCP tool call failed."
    assert "secret" not in response.text
    assert "internal" not in response.text


def test_gateway_timeout_creates_failed_execution(client: TestClient) -> None:
    setup = setup_gateway(client)
    setup["app"].dependency_overrides[get_mcp_execution_adapter] = lambda: TimeoutExecutionAdapter()

    response = call_tool(client, setup)
    execution = client.get(f"/api/v1/executions/{response.json()['execution_id']}")

    assert response.status_code == 200
    assert response.json()["status"] == "failed"
    assert execution.json()["status"] == "failed"
    assert "private timeout detail" not in response.text


def test_disabled_gateway_tool_call_is_rejected(client: TestClient) -> None:
    setup = setup_gateway(client)
    disabled = client.patch(
        f"/api/v1/agents/{setup['tool']['agent_id']}/tools/{setup['tool']['id']}",
        json={"is_enabled": False},
    )
    assert disabled.status_code == 200

    response = call_tool(client, setup)

    assert response.status_code == 404
    assert response.json() == {"detail": "Gateway tool not found."}


def test_non_executable_gateway_tool_call_is_rejected(client: TestClient) -> None:
    setup = setup_gateway(client)
    reviewed = client.post(
        f"/api/v1/tool-governance/{setup['tool']['id']}/review",
        json={"risk_level": "medium", "permission": "read"},
    )
    assert reviewed.status_code == 200

    response = call_tool(client, setup)

    assert response.status_code == 404
    assert response.json() == {"detail": "Gateway tool not found."}


def test_gateway_idempotency_prevents_duplicate_upstream_call(client: TestClient) -> None:
    setup = setup_gateway(client)
    adapter = ExecutionAdapter()
    setup["app"].dependency_overrides[get_mcp_execution_adapter] = lambda: adapter

    first = call_tool(client, setup, idempotency_key="payment-42")
    second = call_tool(client, setup, idempotency_key="payment-42")

    assert first.status_code == 200
    assert second.status_code == 200
    assert second.json()["execution_id"] == first.json()["execution_id"]
    assert second.json()["idempotent_replay"] is True
    assert second.json()["result"] is None
    assert adapter.calls == 1


def test_gateway_audit_events_are_created(client: TestClient) -> None:
    setup = setup_gateway(client)
    setup["app"].dependency_overrides[get_mcp_execution_adapter] = lambda: ExecutionAdapter()

    call_tool(client, setup)

    requested = client.get(
        "/api/v1/audit-logs",
        params={"action": "mcp_gateway.call_requested"},
    )
    succeeded = client.get(
        "/api/v1/audit-logs",
        params={"action": "mcp_gateway.call_succeeded"},
    )
    assert requested.json()["total"] == 1
    assert succeeded.json()["total"] == 1
    assert setup["token"]["token"] not in requested.text


def test_unreviewed_gateway_tool_call_is_rejected(client: TestClient) -> None:
    server = client.post(
        "/api/v1/mcp-servers",
        json={"name": "Unreviewed Gateway", "server_url": "https://unreviewed.example.com/mcp"},
    ).json()
    app = cast(FastAPI, client.app)
    app.dependency_overrides[get_mcp_discovery_adapter] = lambda: DiscoveryAdapter()
    client.post(f"/api/v1/mcp-servers/{server['id']}/sync")
    tool = client.get("/api/v1/tool-governance").json()["items"][0]
    token = client.post(
        "/api/v1/mcp-gateway-tokens",
        json={"mcp_server_id": server["id"], "name": "Unreviewed token"},
    ).json()["token"]

    response = client.post(
        f"/api/v1/mcp-gateway/{server['id']}/tools/{tool['id']}/call",
        headers=gateway_headers(token),
        json={"input_payload": {}},
    )

    assert response.status_code == 404
    assert response.json() == {"detail": "Gateway tool not found."}


def test_gateway_call_rate_limit_returns_429(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    setup = setup_gateway(client)
    setup["app"].dependency_overrides[get_mcp_execution_adapter] = lambda: ExecutionAdapter()
    monkeypatch.setenv("GATEWAY_CALL_RATE_LIMIT_ATTEMPTS", "1")
    get_settings.cache_clear()
    reset_rate_limit_backend()

    first = call_tool(client, setup)
    limited = call_tool(client, setup)

    assert first.status_code == 200
    assert limited.status_code == 429
    assert limited.headers["Retry-After"] == "60"


def call_tool(
    client: TestClient,
    setup: dict[str, Any],
    *,
    approval_id: str | None = None,
    idempotency_key: str | None = None,
) -> Any:
    return client.post(
        f"/api/v1/mcp-gateway/{setup['server']['id']}/tools/{setup['tool']['id']}/call",
        headers=gateway_headers(setup["token"]["token"]),
        json={
            "input_payload": {"account_id": "123"},
            "approval_id": approval_id,
            "idempotency_key": idempotency_key,
        },
    )
