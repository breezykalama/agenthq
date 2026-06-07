from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class DiscoveredMCPTool:
    name: str
    description: str | None = None


class MCPDiscoveryError(Exception):
    pass


class MCPDiscoveryAdapter(Protocol):
    def discover_tools(self, server_url: str) -> list[DiscoveredMCPTool]: ...


class MockMCPDiscoveryAdapter:
    def discover_tools(self, server_url: str) -> list[DiscoveredMCPTool]:
        if "fail" in server_url.lower():
            raise MCPDiscoveryError("Mock MCP discovery failed.")

        prefix = "Updated " if "updated" in server_url.lower() else ""
        return [
            DiscoveredMCPTool("list_customers", f"{prefix}List customer records."),
            DiscoveredMCPTool("create_ticket", f"{prefix}Create a support ticket."),
            DiscoveredMCPTool("summarize_policy", f"{prefix}Summarize a policy document."),
        ]


def get_mcp_discovery_adapter() -> MCPDiscoveryAdapter:
    return MockMCPDiscoveryAdapter()
