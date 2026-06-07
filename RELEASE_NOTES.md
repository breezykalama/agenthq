# AgentHQ v0.2.0 — MCP Server Registration & Tool Discovery

AgentHQ v0.2.0 expands the governance platform with MCP server registration and adapter-based tool discovery.

## Highlights

* Added MCP Server Registration
* Added MCP Tool Discovery via adapter-based discovery
* Added linked agent creation during sync
* Added idempotent tool sync
* Added MCP sync audit logs
* Added MCP server dashboard counts
* Increased automated test coverage to 170 passing tests

## MCP Registration

Registered MCP servers track connection status, linked agents, synchronization timestamps, and the latest discovery error. Soft-deleted servers remain excluded from active registry results and dashboard counts.

## Tool Discovery

The v0.2.0 discovery flow uses a mock/local adapter behind an interface designed for future real MCP clients. Successful synchronization creates or reuses a linked agent and upserts discovered tools into the Agent Tools Registry.

Repeated synchronization does not duplicate tools. Discovery can update tool descriptions while preserving manually governed permission and risk-level settings.

## Auditability

AgentHQ records `mcp_server.synced` and `mcp_server.sync_failed` audit events with structured before/after snapshots.

## Verification

* 170 automated backend tests passing
* Ruff clean
* MyPy clean
* MCP migrations verified against PostgreSQL
