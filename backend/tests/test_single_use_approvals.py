"""Approvals are single use and must be at least as risky as the tool they authorize."""

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
from app.core.approval_risk import approval_risk_covers, covering_risk_levels
from app.models.agent import AgentRiskLevel

INVALID_APPROVAL = {"detail": "Approval is invalid for this gateway tool call."}


class Discovery:
    def discover_tools(self, target: MCPDiscoveryTarget) -> list[DiscoveredMCPTool]:
        return [DiscoveredMCPTool("transfer_funds", "Transfer funds.", {"type": "object"})]


class Upstream:
    """Counts upstream calls; optionally fails the way a real upstream can."""

    def __init__(self, error: Exception | None = None) -> None:
        self.calls = 0
        self.error = error

    def call_tool(
        self,
        target: MCPDiscoveryTarget,
        tool_name: str,
        arguments: dict[str, object],
    ) -> MCPToolExecutionResult:
        self.calls += 1
        if self.error is not None:
            raise self.error
        return MCPToolExecutionResult(payload={"content": [{"type": "text", "text": "done"}]})


def gateway(client: TestClient, *, tool_risk: str = "high") -> dict[str, Any]:
    app = cast(FastAPI, client.app)
    server = client.post(
        "/api/v1/mcp-servers",
        json={"name": "Payments MCP", "server_url": "https://payments.example.com/mcp"},
    ).json()
    app.dependency_overrides[get_mcp_discovery_adapter] = lambda: Discovery()
    assert client.post(f"/api/v1/mcp-servers/{server['id']}/sync").status_code == 200
    tool = client.get("/api/v1/tool-governance").json()["items"][0]
    assert (
        client.post(
            f"/api/v1/tool-governance/{tool['id']}/review",
            json={"risk_level": tool_risk, "permission": "execute"},
        ).status_code
        == 200
    )
    token = client.post(
        "/api/v1/mcp-gateway-tokens",
        json={"mcp_server_id": server["id"], "name": "Payments client"},
    ).json()["token"]
    return {"app": app, "server": server, "tool": tool, "token": token}


def use_upstream(setup: dict[str, Any], upstream: Upstream) -> Upstream:
    setup["app"].dependency_overrides[get_mcp_execution_adapter] = lambda: upstream
    return upstream


def approved(client: TestClient, setup: dict[str, Any], risk_level: str = "high") -> str:
    approval = client.post(
        "/api/v1/approvals",
        json={
            "agent_id": setup["tool"]["agent_id"],
            "requested_action": "transfer_funds",
            "risk_level": risk_level,
        },
    ).json()
    assert client.post(f"/api/v1/approvals/{approval['id']}/approve").status_code == 200
    return cast(str, approval["id"])


def call(client: TestClient, setup: dict[str, Any], approval_id: str | None) -> Any:
    return client.post(
        f"/api/v1/mcp-gateway/{setup['server']['id']}/tools/{setup['tool']['id']}/call",
        headers={"Authorization": f"Bearer {setup['token']}"},
        json={"input_payload": {"account": "1", "amount": 10}, "approval_id": approval_id},
    )


def approval(client: TestClient, approval_id: str) -> dict[str, Any]:
    return cast(dict[str, Any], client.get(f"/api/v1/approvals/{approval_id}").json())


def audit(client: TestClient, action: str) -> list[dict[str, Any]]:
    response = client.get("/api/v1/audit-logs", params={"action": action, "limit": 100})
    return cast(list[dict[str, Any]], response.json()["items"])


def test_first_use_succeeds_and_second_use_is_refused(client: TestClient) -> None:
    setup = gateway(client)
    upstream = use_upstream(setup, Upstream())
    approval_id = approved(client, setup)

    first = call(client, setup, approval_id)
    second = call(client, setup, approval_id)

    assert first.status_code == 200
    assert first.json()["status"] == "succeeded"
    assert second.status_code == 422
    assert second.json() == INVALID_APPROVAL
    assert upstream.calls == 1
    consumed = approval(client, approval_id)
    assert consumed["status"] == "approved"
    assert consumed["consumed_at"] is not None
    assert consumed["consumed_by_execution_id"] == first.json()["execution_id"]
    consumption = audit(client, "approval.consumed")
    assert len(consumption) == 1
    assert consumption[0]["entity_id"] == approval_id
    assert consumption[0]["metadata"]["execution_id"] == first.json()["execution_id"]
    assert "account" not in str(consumption)  # no execution inputs in the audit record
    denials = audit(client, "security.access_denied")
    assert any(entry["reason"] == "Approval has already been used." for entry in denials)


@pytest.mark.parametrize(
    "error",
    [MCPExecutionError("upstream failed"), TimeoutError("upstream timed out")],
)
def test_failed_or_timed_out_call_does_not_restore_the_approval(
    client: TestClient,
    error: Exception,
) -> None:
    setup = gateway(client)
    failing = use_upstream(setup, Upstream(error))
    approval_id = approved(client, setup)

    first = call(client, setup, approval_id)
    healthy = use_upstream(setup, Upstream())
    retry = call(client, setup, approval_id)

    assert first.json()["status"] == "failed"
    assert failing.calls == 1
    assert retry.status_code == 422
    assert healthy.calls == 0
    assert approval(client, approval_id)["consumed_by_execution_id"] == first.json()["execution_id"]


@pytest.mark.parametrize("approval_risk", ["low", "medium"])
def test_lower_risk_approval_is_refused_and_not_consumed(
    client: TestClient,
    approval_risk: str,
) -> None:
    setup = gateway(client, tool_risk="high")
    upstream = use_upstream(setup, Upstream())
    approval_id = approved(client, setup, risk_level=approval_risk)

    response = call(client, setup, approval_id)

    assert response.status_code == 422
    assert upstream.calls == 0
    assert approval(client, approval_id)["consumed_at"] is None
    denials = audit(client, "security.access_denied")
    assert any("lower than the tool's risk level" in (entry["reason"] or "") for entry in denials)


@pytest.mark.parametrize("approval_risk", ["high", "critical"])
def test_equal_or_higher_risk_approval_is_accepted(client: TestClient, approval_risk: str) -> None:
    setup = gateway(client, tool_risk="high")
    upstream = use_upstream(setup, Upstream())

    response = call(client, setup, approved(client, setup, risk_level=approval_risk))

    assert response.json()["status"] == "succeeded"
    assert upstream.calls == 1


def test_blocked_call_does_not_consume_the_approval(client: TestClient) -> None:
    setup = gateway(client)
    upstream = use_upstream(setup, Upstream())
    approval_id = approved(client, setup)
    assert (
        client.post(
            "/api/v1/policy-rules",
            json={
                "name": "Block transfers",
                "scope": "tool",
                "agent_id": setup["tool"]["agent_id"],
                "tool_id": setup["tool"]["id"],
                "risk_level": "low",
                "effect": "block",
            },
        ).status_code
        == 201
    )

    response = call(client, setup, approval_id)

    assert response.json()["status"] == "blocked"
    assert upstream.calls == 0
    assert approval(client, approval_id)["consumed_at"] is None


def test_recorded_executions_respect_consumption_and_risk_without_consuming(
    client: TestClient,
) -> None:
    setup = gateway(client)
    upstream = use_upstream(setup, Upstream())
    approval_id = approved(client, setup)
    agent_id = setup["tool"]["agent_id"]

    def record(risk_level: str) -> Any:
        return client.post(
            "/api/v1/executions",
            json={
                "agent_id": agent_id,
                "action_name": "transfer_funds",
                "risk_level": risk_level,
                "approval_id": approval_id,
            },
        )

    too_risky = record("critical")  # the approval (high) does not cover a critical execution
    recorded = record("high")  # recording does not consume the approval
    gateway_call = call(client, setup, approval_id)  # the single external execution
    after_consumption = record("high")

    assert too_risky.status_code == 409
    assert recorded.status_code == 201
    assert gateway_call.json()["status"] == "succeeded"
    assert upstream.calls == 1
    assert after_consumption.status_code == 409


def test_unknown_or_missing_risk_never_authorizes() -> None:
    assert covering_risk_levels(AgentRiskLevel.HIGH) == {
        AgentRiskLevel.HIGH,
        AgentRiskLevel.CRITICAL,
    }
    assert covering_risk_levels(None) == frozenset()
    assert covering_risk_levels("high") == frozenset()  # unvalidated strings are not trusted
    assert covering_risk_levels("severe") == frozenset()
    assert not approval_risk_covers(None, AgentRiskLevel.LOW)
    assert not approval_risk_covers("critical", AgentRiskLevel.LOW)
    assert not approval_risk_covers(AgentRiskLevel.CRITICAL, None)
    assert approval_risk_covers(AgentRiskLevel.CRITICAL, AgentRiskLevel.LOW)
