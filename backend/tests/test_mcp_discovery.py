from contextlib import asynccontextmanager
from types import SimpleNamespace
from typing import Any

import anyio
import pytest
from pydantic import ValidationError

from app.adapters import mcp_discovery
from app.adapters.mcp_discovery import (
    DiscoveredMCPTool,
    MCPDiscoveryError,
    MCPDiscoveryTarget,
    MockMCPDiscoveryAdapter,
    RealMCPDiscoveryAdapter,
    build_auth_headers,
    get_mcp_discovery_adapter,
    list_all_tools,
)
from app.core.config import Settings, get_settings
from app.models.mcp_server import MCPAuthType, MCPTransportType


def target(**values: object) -> MCPDiscoveryTarget:
    defaults: dict[str, object] = {"server_url": "https://mcp.example.com/mcp"}
    defaults.update(values)
    return MCPDiscoveryTarget(**defaults)  # type: ignore[arg-type]


def test_mock_mode_selects_mock_adapter(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MCP_DISCOVERY_MODE", "mock")
    get_settings.cache_clear()
    try:
        adapter = get_mcp_discovery_adapter()
        assert isinstance(adapter, MockMCPDiscoveryAdapter)
        assert len(adapter.discover_tools(target())) == 3
    finally:
        get_settings.cache_clear()


def test_real_mode_selects_real_adapter(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MCP_DISCOVERY_MODE", "real")
    get_settings.cache_clear()
    try:
        assert isinstance(get_mcp_discovery_adapter(), RealMCPDiscoveryAdapter)
    finally:
        get_settings.cache_clear()


def test_invalid_mcp_discovery_mode_rejected() -> None:
    with pytest.raises(ValidationError):
        Settings(
            _env_file=None,
            DATABASE_URL="postgresql://agenthq:agenthq@localhost:5432/agenthq",
            MCP_DISCOVERY_MODE="unsupported",
        )


@pytest.mark.parametrize(
    ("tools", "expected"),
    [
        (
            [
                SimpleNamespace(name="list_customers", description="List customers."),
                SimpleNamespace(name="create_ticket", description=None),
            ],
            [
                DiscoveredMCPTool("list_customers", "List customers."),
                DiscoveredMCPTool("create_ticket", None),
            ],
        ),
        ([], []),
    ],
)
def test_real_adapter_maps_tools_list(
    tools: list[SimpleNamespace],
    expected: list[DiscoveredMCPTool],
) -> None:
    class FakeSession:
        async def list_tools(self, cursor: str | None = None) -> SimpleNamespace:
            return SimpleNamespace(tools=tools, nextCursor=None)

    assert anyio.run(list_all_tools, FakeSession()) == expected  # type: ignore[arg-type]


def test_real_adapter_connection_failure_is_sanitized(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    @asynccontextmanager
    async def failing_transport(
        discovery_target: MCPDiscoveryTarget,
        headers: dict[str, str],
    ) -> Any:
        raise RuntimeError("password=secret internal.example")
        yield

    monkeypatch.setattr(mcp_discovery, "open_mcp_transport", failing_transport)

    with pytest.raises(MCPDiscoveryError, match="Real MCP discovery failed") as exc_info:
        RealMCPDiscoveryAdapter().discover_tools(target())

    assert "secret" not in str(exc_info.value)
    assert "internal.example" not in str(exc_info.value)


def test_real_adapter_initializes_session_and_maps_tools(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    initialized = False

    @asynccontextmanager
    async def fake_transport(
        discovery_target: MCPDiscoveryTarget,
        headers: dict[str, str],
    ) -> Any:
        yield object(), object()

    class FakeClientSession:
        def __init__(self, *args: object, **kwargs: object) -> None:
            pass

        async def __aenter__(self) -> "FakeClientSession":
            return self

        async def __aexit__(self, *args: object) -> None:
            pass

        async def initialize(self) -> None:
            nonlocal initialized
            initialized = True

        async def list_tools(self, cursor: str | None = None) -> SimpleNamespace:
            return SimpleNamespace(
                tools=[
                    SimpleNamespace(
                        name="govern_payment",
                        description="Govern a payment.",
                        inputSchema={"type": "object"},
                    )
                ],
                nextCursor=None,
            )

    monkeypatch.setattr(mcp_discovery, "open_mcp_transport", fake_transport)
    monkeypatch.setattr(mcp_discovery, "ClientSession", FakeClientSession)

    tools = RealMCPDiscoveryAdapter().discover_tools(target())

    assert initialized is True
    assert tools == [DiscoveredMCPTool("govern_payment", "Govern a payment.")]


def test_real_adapter_timeout_is_sanitized(monkeypatch: pytest.MonkeyPatch) -> None:
    @asynccontextmanager
    async def slow_transport(
        discovery_target: MCPDiscoveryTarget,
        headers: dict[str, str],
    ) -> Any:
        await anyio.sleep(1)
        yield

    monkeypatch.setattr(mcp_discovery, "open_mcp_transport", slow_transport)

    with pytest.raises(MCPDiscoveryError, match="Real MCP discovery failed"):
        RealMCPDiscoveryAdapter().discover_tools(
            target(connect_timeout_seconds=0.01, request_timeout_seconds=0.01)
        )


def test_real_adapter_uses_environment_referenced_auth(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("MCP_AUTH_CUSTOMER", "top-secret-value")

    headers = build_auth_headers(
        target(auth_type=MCPAuthType.BEARER, auth_secret_ref="MCP_AUTH_CUSTOMER")
    )

    assert headers == {"Authorization": "Bearer top-secret-value"}


def test_real_adapter_rejects_missing_referenced_auth() -> None:
    with pytest.raises(MCPDiscoveryError, match="authentication is not configured"):
        build_auth_headers(
            target(auth_type=MCPAuthType.API_KEY, auth_secret_ref="MCP_AUTH_MISSING")
        )


def test_target_supports_sse_transport() -> None:
    assert target(transport_type=MCPTransportType.SSE).transport_type == MCPTransportType.SSE
