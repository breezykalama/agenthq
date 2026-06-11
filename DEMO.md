# AgentHQ Demo Flow

Use this after running PostgreSQL, migrations, the seed script, and the API server.

Base URL:

```text
http://localhost:8000
```

## Authentication

The governance endpoints below require an authenticated user with the appropriate organization
membership and role. Log in first:

```bash
curl -X POST http://localhost:8000/api/v1/auth/login \
  -H "Content-Type: application/json" \
  -d '{
    "email": "admin@agenthq.local",
    "password": "your-password"
  }'
```

Save the returned `access_token` and send it with every protected request:

```text
Authorization: Bearer {access_token}
```

The examples below use `{access_token}` as a placeholder.

## 1. View Dashboard Summary

```bash
curl http://localhost:8000/api/v1/dashboard/summary \
  -H "Authorization: Bearer {access_token}"
```

## 2. View Agents

```bash
curl http://localhost:8000/api/v1/agents \
  -H "Authorization: Bearer {access_token}"
```

Pick the `id` for `Payment Operations Agent` from the response.

## 3. View One Agent's Tools

```bash
curl http://localhost:8000/api/v1/agents/{agent_id}/tools \
  -H "Authorization: Bearer {access_token}"
```

## 4. Evaluate a Policy Decision

```bash
curl -X POST http://localhost:8000/api/v1/policy-decisions/evaluate \
  -H "Authorization: Bearer {access_token}" \
  -H "Content-Type: application/json" \
  -d '{
    "agent_id": "{agent_id}",
    "requested_action": "refund_review",
    "risk_level": "high"
  }'
```

## 5. Create a High-Risk Execution

```bash
curl -X POST http://localhost:8000/api/v1/executions \
  -H "Authorization: Bearer {access_token}" \
  -H "Content-Type: application/json" \
  -d '{
    "agent_id": "{agent_id}",
    "action_name": "refund_review",
    "risk_level": "high",
    "status": "running"
  }'
```

The execution should be marked `requires_approval` unless an approved approval is provided.

## 6. Approve an Approval

List approvals:

```bash
curl http://localhost:8000/api/v1/approvals \
  -H "Authorization: Bearer {access_token}"
```

Approve one pending approval:

```bash
curl -X POST http://localhost:8000/api/v1/approvals/{approval_id}/approve \
  -H "Authorization: Bearer {access_token}" \
  -H "Content-Type: application/json" \
  -d '{
    "approver": "risk-office",
    "decision_reason": "Demo approval granted."
  }'
```

## 7. Create an Incident

```bash
curl -X POST http://localhost:8000/api/v1/incidents \
  -H "Authorization: Bearer {access_token}" \
  -H "Content-Type: application/json" \
  -d '{
    "agent_id": "{agent_id}",
    "title": "Demo incident",
    "description": "Operator recorded a demo governance incident.",
    "severity": "high",
    "reported_by": "demo-operator"
  }'
```

## 8. View Compliance Summary

```bash
curl http://localhost:8000/api/v1/compliance/summary \
  -H "Authorization: Bearer {access_token}"
```

## AgentHQ v0.2.0 MCP Demo Flow

This flow uses the current mock/local MCP discovery adapter. It demonstrates registration, linked agent creation, idempotent tool discovery, auditing, and dashboard counts without real MCP protocol networking.

## 9. Register an MCP Server

```bash
curl -X POST http://localhost:8000/api/v1/mcp-servers \
  -H "Authorization: Bearer {access_token}" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "Customer Operations MCP",
    "description": "Demo MCP server for customer operations.",
    "server_url": "https://mcp.example.com/server"
  }'
```

Save the returned MCP server `id` as `{server_id}`.

## 10. Sync the MCP Server

```bash
curl -X POST http://localhost:8000/api/v1/mcp-servers/{server_id}/sync \
  -H "Authorization: Bearer {access_token}"
```

Save the returned `agent_id`. A successful sync reports `connected`, creates three tools, and sets `last_sync_at`.

## 11. Confirm the Linked Agent

```bash
curl http://localhost:8000/api/v1/agents/{agent_id} \
  -H "Authorization: Bearer {access_token}"
```

The linked agent name should match the registered MCP server name.

## 12. Confirm Discovered Tools

```bash
curl http://localhost:8000/api/v1/agents/{agent_id}/tools \
  -H "Authorization: Bearer {access_token}"
```

The response should include:

* `list_customers`
* `create_ticket`
* `summarize_policy`

Run the sync endpoint again to confirm no duplicate tools are created.

## 13. Confirm the MCP Sync Audit Log

```bash
curl "http://localhost:8000/api/v1/audit-logs?action=mcp_server.synced&entity_id={server_id}" \
  -H "Authorization: Bearer {access_token}"
```

The response should include an `mcp_server.synced` event with before/after snapshots.

## 14. Confirm the Dashboard MCP Server Count

```bash
curl http://localhost:8000/api/v1/dashboard/summary \
  -H "Authorization: Bearer {access_token}"
```

Confirm `total_mcp_servers` and `connected_mcp_servers` include the synced server.
