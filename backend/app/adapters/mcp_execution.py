from dataclasses import dataclass
from typing import Protocol, cast

import anyio
from mcp import ClientSession

from app.adapters.mcp_discovery import MCPDiscoveryTarget, build_auth_headers, open_mcp_transport
from app.core.mcp_urls import validate_mcp_server_url


@dataclass(frozen=True)
class MCPToolExecutionResult:
    payload: dict[str, object]


class MCPExecutionError(Exception):
    pass


class MCPExecutionAdapter(Protocol):
    def call_tool(
        self,
        target: MCPDiscoveryTarget,
        tool_name: str,
        arguments: dict[str, object],
    ) -> MCPToolExecutionResult: ...


class RealMCPExecutionAdapter:
    def call_tool(
        self,
        target: MCPDiscoveryTarget,
        tool_name: str,
        arguments: dict[str, object],
    ) -> MCPToolExecutionResult:
        try:
            return anyio.run(self._call_tool, target, tool_name, arguments)
        except Exception as exc:
            raise MCPExecutionError("Upstream MCP tool call failed.") from exc

    async def _call_tool(
        self,
        target: MCPDiscoveryTarget,
        tool_name: str,
        arguments: dict[str, object],
    ) -> MCPToolExecutionResult:
        validate_mcp_server_url(target.server_url)
        headers = build_auth_headers(target)
        total_timeout = target.connect_timeout_seconds + target.request_timeout_seconds
        with anyio.fail_after(total_timeout):
            async with open_mcp_transport(target, headers) as (read_stream, write_stream):
                async with ClientSession(read_stream, write_stream) as session:
                    await session.initialize()
                    result = await session.call_tool(tool_name, arguments=arguments)
                    return MCPToolExecutionResult(
                        payload=cast(dict[str, object], result.model_dump(mode="json"))
                    )


def get_mcp_execution_adapter() -> MCPExecutionAdapter:
    return RealMCPExecutionAdapter()
