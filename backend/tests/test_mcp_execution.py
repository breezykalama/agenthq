from contextlib import asynccontextmanager
from types import SimpleNamespace
from typing import Any

import pytest

from app.adapters import mcp_execution
from app.adapters.mcp_discovery import MCPDiscoveryTarget
from app.adapters.mcp_execution import MCPExecutionError, RealMCPExecutionAdapter


def test_real_execution_adapter_initializes_session_and_calls_tool(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    called: dict[str, object] = {}

    @asynccontextmanager
    async def fake_transport(
        target: MCPDiscoveryTarget,
        headers: dict[str, str],
    ) -> Any:
        yield object(), object()

    class FakeResult:
        def model_dump(self, *, mode: str) -> dict[str, object]:
            return {"content": [{"type": "text", "text": "complete"}]}

    class FakeSession:
        def __init__(self, *args: object, **kwargs: object) -> None:
            pass

        async def __aenter__(self) -> "FakeSession":
            return self

        async def __aexit__(self, *args: object) -> None:
            pass

        async def initialize(self) -> None:
            called["initialized"] = True

        async def call_tool(self, name: str, *, arguments: dict[str, object]) -> FakeResult:
            called["name"] = name
            called["arguments"] = arguments
            return FakeResult()

    monkeypatch.setattr(mcp_execution, "open_mcp_transport", fake_transport)
    monkeypatch.setattr(mcp_execution, "ClientSession", FakeSession)

    result = RealMCPExecutionAdapter().call_tool(
        MCPDiscoveryTarget(server_url="https://mcp.example.com/mcp"),
        "create_ticket",
        {"subject": "Help"},
    )

    assert called == {
        "initialized": True,
        "name": "create_ticket",
        "arguments": {"subject": "Help"},
    }
    assert result.payload["content"] == [{"type": "text", "text": "complete"}]


def test_real_execution_adapter_sanitizes_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    @asynccontextmanager
    async def failing_transport(
        target: MCPDiscoveryTarget,
        headers: dict[str, str],
    ) -> Any:
        raise RuntimeError("password=secret internal.example")
        yield SimpleNamespace()

    monkeypatch.setattr(mcp_execution, "open_mcp_transport", failing_transport)

    with pytest.raises(MCPExecutionError, match="Upstream MCP tool call failed") as exc_info:
        RealMCPExecutionAdapter().call_tool(
            MCPDiscoveryTarget(server_url="https://mcp.example.com/mcp"),
            "create_ticket",
            {},
        )

    assert "secret" not in str(exc_info.value)
    assert "internal.example" not in str(exc_info.value)
