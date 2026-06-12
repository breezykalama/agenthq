import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import timedelta
from typing import Any, Protocol

import anyio
import httpx
from mcp import ClientSession
from mcp.client.sse import sse_client
from mcp.client.streamable_http import streamable_http_client

from app.core.config import get_settings
from app.core.mcp_urls import validate_mcp_server_url
from app.models.mcp_server import MCPAuthType, MCPTransportType


@dataclass(frozen=True)
class DiscoveredMCPTool:
    name: str
    description: str | None = None


@dataclass(frozen=True)
class MCPDiscoveryTarget:
    server_url: str
    transport_type: MCPTransportType = MCPTransportType.STREAMABLE_HTTP
    auth_type: MCPAuthType = MCPAuthType.NONE
    auth_secret_ref: str | None = None
    request_timeout_seconds: int = 30
    connect_timeout_seconds: int = 10


class MCPDiscoveryError(Exception):
    pass


class MCPDiscoveryAdapter(Protocol):
    def discover_tools(self, target: MCPDiscoveryTarget) -> list[DiscoveredMCPTool]: ...


class MockMCPDiscoveryAdapter:
    def discover_tools(self, target: MCPDiscoveryTarget) -> list[DiscoveredMCPTool]:
        if "fail" in target.server_url.lower():
            raise MCPDiscoveryError("Mock MCP discovery failed.")

        prefix = "Updated " if "updated" in target.server_url.lower() else ""
        return [
            DiscoveredMCPTool("list_customers", f"{prefix}List customer records."),
            DiscoveredMCPTool("create_ticket", f"{prefix}Create a support ticket."),
            DiscoveredMCPTool("summarize_policy", f"{prefix}Summarize a policy document."),
        ]


class RealMCPDiscoveryAdapter:
    def discover_tools(self, target: MCPDiscoveryTarget) -> list[DiscoveredMCPTool]:
        try:
            return anyio.run(self._discover_tools, target)
        except Exception as exc:
            raise MCPDiscoveryError("Real MCP discovery failed.") from exc

    async def _discover_tools(self, target: MCPDiscoveryTarget) -> list[DiscoveredMCPTool]:
        validate_mcp_server_url(target.server_url)
        headers = build_auth_headers(target)
        total_timeout = target.connect_timeout_seconds + target.request_timeout_seconds
        with anyio.fail_after(total_timeout):
            async with open_mcp_transport(target, headers) as (read_stream, write_stream):
                async with ClientSession(
                    read_stream,
                    write_stream,
                    read_timeout_seconds=timedelta(seconds=target.request_timeout_seconds),
                ) as session:
                    await session.initialize()
                    return await list_all_tools(session)


async def list_all_tools(session: ClientSession) -> list[DiscoveredMCPTool]:
    tools: list[DiscoveredMCPTool] = []
    cursor: str | None = None
    while True:
        result = await session.list_tools(cursor=cursor)
        tools.extend(
            DiscoveredMCPTool(name=tool.name, description=tool.description)
            for tool in result.tools
        )
        cursor = result.nextCursor
        if cursor is None:
            return tools


def build_auth_headers(target: MCPDiscoveryTarget) -> dict[str, str]:
    if target.auth_type == MCPAuthType.NONE:
        return {}
    if target.auth_secret_ref is None:
        raise MCPDiscoveryError("MCP authentication is not configured.")
    secret = os.environ.get(target.auth_secret_ref)
    if not secret:
        raise MCPDiscoveryError("MCP authentication is not configured.")
    if target.auth_type == MCPAuthType.BEARER:
        return {"Authorization": f"Bearer {secret}"}
    return {"X-API-Key": secret}


@asynccontextmanager
async def open_mcp_transport(
    target: MCPDiscoveryTarget,
    headers: dict[str, str],
) -> AsyncIterator[tuple[Any, Any]]:
    timeout = httpx.Timeout(
        target.request_timeout_seconds,
        connect=target.connect_timeout_seconds,
    )
    if target.transport_type == MCPTransportType.STREAMABLE_HTTP:
        async with httpx.AsyncClient(
            headers=headers,
            timeout=timeout,
            follow_redirects=False,
        ) as client:
            async with streamable_http_client(
                target.server_url,
                http_client=client,
            ) as (read_stream, write_stream, _):
                yield read_stream, write_stream
        return

    async with sse_client(
        target.server_url,
        headers=headers,
        timeout=target.connect_timeout_seconds,
        sse_read_timeout=target.request_timeout_seconds,
        httpx_client_factory=no_redirect_http_client_factory,
    ) as (read_stream, write_stream):
        yield read_stream, write_stream


def no_redirect_http_client_factory(
    headers: dict[str, str] | None = None,
    timeout: httpx.Timeout | None = None,
    auth: httpx.Auth | None = None,
) -> httpx.AsyncClient:
    return httpx.AsyncClient(
        headers=headers,
        timeout=timeout,
        auth=auth,
        follow_redirects=False,
    )


def get_mcp_discovery_adapter() -> MCPDiscoveryAdapter:
    if get_settings().mcp_discovery_mode == "real":
        return RealMCPDiscoveryAdapter()
    return MockMCPDiscoveryAdapter()
