# AgentHQ Demo Flow

Use this after running PostgreSQL, migrations, the seed script, and the API server.

Base URL:

```text
http://localhost:8000
```

## 1. View Dashboard Summary

```bash
curl http://localhost:8000/api/v1/dashboard/summary
```

## 2. View Agents

```bash
curl http://localhost:8000/api/v1/agents
```

Pick the `id` for `Payment Operations Agent` from the response.

## 3. View One Agent's Tools

```bash
curl http://localhost:8000/api/v1/agents/{agent_id}/tools
```

## 4. Evaluate a Policy Decision

```bash
curl -X POST http://localhost:8000/api/v1/policy-decisions/evaluate \
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
curl http://localhost:8000/api/v1/approvals
```

Approve one pending approval:

```bash
curl -X POST http://localhost:8000/api/v1/approvals/{approval_id}/approve \
  -H "Content-Type: application/json" \
  -d '{
    "approver": "risk-office",
    "decision_reason": "Demo approval granted."
  }'
```

## 7. Create an Incident

```bash
curl -X POST http://localhost:8000/api/v1/incidents \
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
curl http://localhost:8000/api/v1/compliance/summary
```
