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

## Idempotency and Retries

An idempotency key is scoped to the gateway credential and the tool. AgentHQ reserves the key
before it calls the upstream MCP server, so a key dispatches **at most once**, including when
several requests with the same key arrive at the same time. Requests without a key have no
duplicate protection: send a key with every side-effecting call.

The request is identified by a fingerprint of the server, tool, input arguments and approval.
Only the fingerprint is stored, not the arguments.

| Situation | REST response | MCP `tools/call` response |
| --- | --- | --- |
| New key | The call is processed | The call is processed |
| Key completed, same request | `200` with the original outcome and `"idempotent_replay": true`; nothing is re-sent upstream | The original outcome |
| Key in progress, or outcome unknown | `409`: "A request with this idempotency key is in progress or its outcome is unknown." | JSON-RPC error `-32009` with the same message |
| Key already used with a different request | `409`: "This idempotency key was already used with a different request." | JSON-RPC error `-32009` with the same message |

* **Completed outcomes replay.** Succeeded, failed (including upstream errors and timeouts),
  blocked and approval-required results are stored and returned unchanged for the same key and
  request. To try a failed call again, use a new key.
* **In progress or unknown.** A `409` for an in-progress key means another request holds it.
  If AgentHQ stopped after dispatching the call and before recording its result, the outcome
  is unknown and the key stays reserved permanently: AgentHQ never re-sends it.
* **Different request, same key.** Changing the arguments or the approval under a used key
  returns `409`. Argument order does not matter.
* **Approved operations need a new key.** A request answered `requires_approval` is completed
  under its key. Submitting the operation again with its new `approval_id` is a different
  request: use a new idempotency key. An approval is consumed by the single call it authorizes
  and is never consumed by a replay or a `409`.
* **At most once, not exactly once.** AgentHQ guarantees it sends a given key upstream at most
  once. It cannot guarantee end-to-end exactly-once execution: the upstream system may have
  performed the operation even when no result was recorded. Before authorizing the operation
  again under a new key after an unknown outcome, verify in the upstream system whether it
  already happened.

## Production Enforcement Boundary

AgentHQ can enforce only traffic routed through AgentHQ Gateway. For strict enforcement:

* Do not give agents direct upstream MCP credentials.
* Restrict upstream MCP network access so only AgentHQ can reach it.
* Store AgentHQ credentials in a secure secret manager.
* Rotate and revoke credentials regularly.

Agent-to-agent communication is not implemented.
