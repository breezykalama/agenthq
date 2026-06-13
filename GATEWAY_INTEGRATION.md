# AgentHQ Dual-Protocol Governed Gateway

AgentHQ Gateway lets external AI agents access governed MCP tools through either a REST API or a
standards-compatible MCP Streamable HTTP endpoint. Both protocols use the same authorization,
policy, approval, execution, audit, rate-limit, and upstream forwarding pipeline.

## Security Model

An Agent Gateway Credential identifies one registered AgentHQ agent. It is scoped to the current
organization and an explicit set of MCP servers linked to that agent. Callers never provide a
trusted `agent_id` or `organization_id`.

Credentials are hashed at rest, shown only on creation or rotation, revocable, expirable, and rate
limited. Draft and active agents may use the gateway. Disabled, archived, and soft-deleted agents
are denied.

## Create a Credential

Organization admins create credentials from the MCP Servers page or:

```http
POST /api/v1/agent-gateway-credentials
Authorization: Bearer <user-jwt>
Content-Type: application/json

{
  "agent_id": "<agent-id>",
  "allowed_mcp_server_ids": ["<server-id>"],
  "name": "Production agent runtime"
}
```

Store the returned raw credential in the calling platform's secret manager. AgentHQ does not show
it again.

## REST Gateway

```http
GET  /api/v1/gateway/mcp-servers
GET  /api/v1/gateway/mcp-servers/{server_id}/tools
POST /api/v1/gateway/mcp-servers/{server_id}/tools/{tool_id}/call
Authorization: Bearer <agent-gateway-credential>
```

Tool calls accept `input_payload`, optional `approval_id`, and optional `idempotency_key`.

## MCP Streamable HTTP Gateway

Configure MCP-compatible clients with:

```text
URL: https://<agenthq-host>/api/v1/mcp/<server-id>
Authorization: Bearer <agent-gateway-credential>
```

The endpoint supports `initialize`, `notifications/initialized`, `tools/list`, and `tools/call`.
For `tools/call`, an approval or idempotency key may be supplied in `params._meta`:

```json
{
  "jsonrpc": "2.0",
  "id": 1,
  "method": "tools/call",
  "params": {
    "name": "create_ticket",
    "arguments": {"customer_id": "123"},
    "_meta": {
      "approval_id": "<approved-approval-id>",
      "idempotency_key": "ticket-123"
    }
  }
}
```

The compatibility fallback fields `_agenthq_approval_id` and `_agenthq_idempotency_key` may instead
be placed in `arguments`; AgentHQ removes them before forwarding the tool call.

## Production Enforcement Boundary

AgentHQ can enforce only traffic routed through AgentHQ Gateway. For strict enforcement:

* Do not give agents direct upstream MCP credentials.
* Restrict upstream MCP network access so only AgentHQ can reach it.
* Store AgentHQ credentials in a secure secret manager.
* Rotate and revoke credentials regularly.

Agent-to-agent communication is not implemented.
