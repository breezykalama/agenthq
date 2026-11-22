"""Gateway idempotency keys are reserved before dispatch: at most one upstream call per key."""

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

IN_PROGRESS = {
    "detail": "A request with this idempotency key is in progress or its outcome is unknown."
}
MISMATCH = {"detail": "This idempotency key was already used with a different request."}


class Discovery:
    def discover_tools(self, target: MCPDiscoveryTarget) -> list[DiscoveredMCPTool]:
        return [
            DiscoveredMCPTool("transfer_funds", "Transfer funds.", {"type": "object"}),
            DiscoveredMCPTool("refund_payment", "Refund a payment.", {"type": "object"}),
        ]


class Upstream:
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


def gateway(client: TestClient, *, risk_level: str = "medium") -> dict[str, Any]:
    app = cast(FastAPI, client.app)
    server = client.post(
        "/api/v1/mcp-servers",
        json={"name": "Payments MCP", "server_url": "https://payments.example.com/mcp"},
    ).json()
    app.dependency_overrides[get_mcp_discovery_adapter] = lambda: Discovery()
    assert client.post(f"/api/v1/mcp-servers/{server['id']}/sync").status_code == 200
    tools = {tool["name"]: tool for tool in client.get("/api/v1/tool-governance").json()["items"]}
    for tool in tools.values():
        review = client.post(
            f"/api/v1/tool-governance/{tool['id']}/review",
            json={"risk_level": risk_level, "permission": "execute"},
        )
        assert review.status_code == 200
    return {"app": app, "server": server, "tools": tools, "token": new_token(client, server)}


def new_token(client: TestClient, server: dict[str, Any]) -> str:
    response = client.post(
        "/api/v1/mcp-gateway-tokens",
        json={"mcp_server_id": server["id"], "name": "Payments client"},
    )
    assert response.status_code == 201
    return cast(str, response.json()["token"])


def use_upstream(setup: dict[str, Any], upstream: Upstream) -> Upstream:
    setup["app"].dependency_overrides[get_mcp_execution_adapter] = lambda: upstream
    return upstream


def call(
    client: TestClient,
    setup: dict[str, Any],
    key: str | None,
    *,
    tool: str = "transfer_funds",
    payload: dict[str, object] | None = None,
    approval_id: str | None = None,
    token: str | None = None,
) -> Any:
    tool_id = setup["tools"][tool]["id"]
    return client.post(
        f"/api/v1/mcp-gateway/{setup['server']['id']}/tools/{tool_id}/call",
        headers={"Authorization": f"Bearer {token or setup['token']}"},
        json={
            "input_payload": payload if payload is not None else {"account": "1", "amount": 10},
            "approval_id": approval_id,
            "idempotency_key": key,
        },
    )


def approved(client: TestClient, setup: dict[str, Any], risk_level: str = "high") -> str:
    approval = client.post(
        "/api/v1/approvals",
        json={
            "agent_id": setup["tools"]["transfer_funds"]["agent_id"],
            "requested_action": "transfer_funds",
            "risk_level": risk_level,
        },
    ).json()
    assert client.post(f"/api/v1/approvals/{approval['id']}/approve").status_code == 200
    return cast(str, approval["id"])


def approval(client: TestClient, approval_id: str) -> dict[str, Any]:
    return cast(dict[str, Any], client.get(f"/api/v1/approvals/{approval_id}").json())


def test_sequential_retry_replays_without_dispatch(client: TestClient) -> None:
    setup = gateway(client)
    upstream = use_upstream(setup, Upstream())

    first = call(client, setup, "payment-42")
    second = call(client, setup, "payment-42")

    assert first.json()["status"] == "succeeded"
    assert second.status_code == 200
    assert second.json()["idempotent_replay"] is True
    assert second.json()["execution_id"] == first.json()["execution_id"]
    assert upstream.calls == 1


@pytest.mark.parametrize(
    "error",
    [MCPExecutionError("upstream failed"), TimeoutError("upstream timed out")],
)
def test_completed_upstream_failure_replays_without_redispatch(
    client: TestClient,
    error: Exception,
) -> None:
    setup = gateway(client)
    failing = use_upstream(setup, Upstream(error))
    first = call(client, setup, "payment-43")
    healthy = use_upstream(setup, Upstream())

    retry = call(client, setup, "payment-43")

    assert first.json()["status"] == "failed"
    assert retry.status_code == 200
    assert retry.json()["status"] == "failed"
    assert retry.json()["idempotent_replay"] is True
    assert (failing.calls, healthy.calls) == (1, 0)


def test_unresolved_reservation_prevents_redispatch(client: TestClient) -> None:
    """A process that stops after dispatching leaves the key reserved with an unknown outcome."""
    setup = gateway(client)
    crashing = use_upstream(setup, Upstream(RuntimeError("worker lost mid-call")))
    with pytest.raises(RuntimeError):
        call(client, setup, "payment-44")
    healthy = use_upstream(setup, Upstream())

    retry = call(client, setup, "payment-44")

    assert retry.status_code == 409
    assert retry.json() == IN_PROGRESS
    assert (crashing.calls, healthy.calls) == (1, 0)


def test_same_key_with_different_request_is_refused(client: TestClient) -> None:
    setup = gateway(client)
    upstream = use_upstream(setup, Upstream())
    call(client, setup, "payment-45", payload={"account": "1", "amount": 10})

    changed = call(client, setup, "payment-45", payload={"account": "1", "amount": 9000})
    reordered = call(client, setup, "payment-45", payload={"amount": 10, "account": "1"})

    assert changed.status_code == 409
    assert changed.json() == MISMATCH
    assert reordered.status_code == 200  # canonical form: key order does not matter
    assert reordered.json()["idempotent_replay"] is True
    assert upstream.calls == 1


def test_keys_are_independent_across_tools_and_tokens(client: TestClient) -> None:
    setup = gateway(client)
    upstream = use_upstream(setup, Upstream())

    call(client, setup, "shared-key")
    other_tool = call(client, setup, "shared-key", tool="refund_payment")
    other_token = call(client, setup, "shared-key", token=new_token(client, setup["server"]))

    for response in (other_tool, other_token):
        assert response.json()["status"] == "succeeded"
        assert not response.json().get("idempotent_replay")
    assert upstream.calls == 3


def test_mcp_protocol_reports_idempotency_conflict(client: TestClient) -> None:
    setup = gateway(client)
    upstream = use_upstream(setup, Upstream())
    credential = client.post(
        "/api/v1/agent-gateway-credentials",
        json={
            "agent_id": setup["tools"]["transfer_funds"]["agent_id"],
            "allowed_mcp_server_ids": [setup["server"]["id"]],
            "name": "Agent runtime",
        },
    ).json()["token"]

    def mcp_call(account: str) -> Any:
        return client.post(
            f"/api/v1/mcp/{setup['server']['id']}",
            headers={"Authorization": f"Bearer {credential}"},
            json={
                "jsonrpc": "2.0",
                "id": 7,
                "method": "tools/call",
                "params": {
                    "name": "transfer_funds",
                    "arguments": {"account": account, "_agenthq_idempotency_key": "mcp-1"},
                },
            },
        )

    first = mcp_call("1")
    conflict = mcp_call("2")

    assert first.json()["result"]["content"][0]["text"] == "done"
    assert conflict.json()["error"] == {"code": -32009, "message": MISMATCH["detail"]}
    assert upstream.calls == 1


# --- Approval-gated calls ------------------------------------------------------------------


def test_replay_of_approved_call_does_not_reuse_or_consume_the_approval(
    client: TestClient,
) -> None:
    setup = gateway(client, risk_level="high")
    upstream = use_upstream(setup, Upstream())
    approval_id = approved(client, setup)

    first = call(client, setup, "approved-1", approval_id=approval_id)
    replay = call(client, setup, "approved-1", approval_id=approval_id)

    assert first.json()["status"] == "succeeded"
    assert replay.status_code == 200
    assert replay.json()["idempotent_replay"] is True
    assert upstream.calls == 1
    assert approval(client, approval_id)["consumed_by_execution_id"] == first.json()["execution_id"]


def test_idempotency_conflicts_do_not_consume_approvals(client: TestClient) -> None:
    setup = gateway(client, risk_level="high")
    first_approval = approved(client, setup)
    use_upstream(setup, Upstream(RuntimeError("worker lost mid-call")))
    with pytest.raises(RuntimeError):
        call(client, setup, "approved-2", approval_id=first_approval)
    upstream = use_upstream(setup, Upstream())
    second_approval = approved(client, setup)

    in_progress = call(client, setup, "approved-2", approval_id=first_approval)
    mismatch = call(client, setup, "approved-2", approval_id=second_approval)
    fresh_key = call(client, setup, "approved-3", approval_id=second_approval)

    assert in_progress.status_code == 409
    assert mismatch.status_code == 409
    assert upstream.calls == 1  # only the fresh key dispatched
    assert fresh_key.json()["status"] == "succeeded"
    assert (
        approval(client, second_approval)["consumed_by_execution_id"]
        == (fresh_key.json()["execution_id"])
    )


def test_approval_rules_still_apply_with_idempotency_keys(client: TestClient) -> None:
    setup = gateway(client, risk_level="high")
    upstream = use_upstream(setup, Upstream())
    low = approved(client, setup, risk_level="medium")
    used = approved(client, setup)
    assert call(client, setup, "use-it", approval_id=used).json()["status"] == "succeeded"

    no_approval = call(client, setup, "gated-1")
    too_low = call(client, setup, "gated-2", approval_id=low)
    reused = call(client, setup, "gated-3", approval_id=used)
    after_refusal = call(client, setup, "gated-2", approval_id=used)

    assert no_approval.json()["status"] == "requires_approval"
    assert too_low.status_code == 422
    assert reused.status_code == 422
    assert after_refusal.status_code == 422  # a refused attempt left no reservation behind
    assert approval(client, low)["consumed_at"] is None
    assert upstream.calls == 1
