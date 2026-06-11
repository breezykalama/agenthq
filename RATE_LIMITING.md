# AgentHQ Rate Limiting

AgentHQ applies centralized abuse protection at the FastAPI authorization boundary. Rate limits
do not replace authentication, organization isolation, RBAC, or audit logging.

## Protected Endpoint Categories

| Category | Protected operations | Default limit |
| --- | --- | --- |
| Authentication | Login, registration, organization bootstrap, invite acceptance | 10 per 60 seconds |
| Organization invites | Create and revoke | 10 per 60 seconds |
| Approval actions | Request, approve, reject, and cancel | 30 per 60 seconds |
| Executions | Create and update simulated executions | 60 per 60 seconds |
| MCP sync | Sync one registered MCP server | 5 per 60 seconds |
| Policy testing | Evaluate policy decisions | 60 per 60 seconds |
| Compliance access | Summary, agent report, and incident report reads | 30 per 60 seconds |

AgentHQ currently has no token refresh, password reset/email, tool execution, or compliance export
endpoint. Those categories must be added to the centralized limiter when introduced.

## Rate Limit Keys

- Unauthenticated authentication requests use the client IP address.
- Login also uses a SHA-256-derived identifier key; raw email addresses are not logged or stored.
- Authenticated sensitive requests use the current organization ID, actor user ID, action, and,
  where applicable, the target resource ID.
- Organization and actor context is derived by FastAPI after authentication and membership checks.
  It is never accepted from a request body.

## Redis And Local Behavior

Production should set `REDIS_URL` and use Redis fixed-window counters shared across API instances.
If rate limiting is enabled in production and Redis is not configured or unavailable, sensitive
requests fail closed with `503 Service Unavailable`.

Development and tests use an in-memory sliding-window backend. This backend is intentionally not
used in production because counters would not be shared across processes or instances.

Tests and local tooling can explicitly set `RATE_LIMITS_ENABLED=false` when rate limiting is not
part of the scenario being exercised.

## Configuration

```text
RATE_LIMITS_ENABLED=true
REDIS_URL=redis://...
AUTH_RATE_LIMIT_ATTEMPTS=10
AUTH_RATE_LIMIT_WINDOW_SECONDS=60
SENSITIVE_RATE_LIMIT_WINDOW_SECONDS=60
INVITE_CREATE_RATE_LIMIT_ATTEMPTS=10
APPROVAL_RATE_LIMIT_ATTEMPTS=30
EXECUTION_RATE_LIMIT_ATTEMPTS=60
MCP_SYNC_RATE_LIMIT_ATTEMPTS=5
POLICY_DECISION_RATE_LIMIT_ATTEMPTS=60
COMPLIANCE_RATE_LIMIT_ATTEMPTS=30
```

## Responses And Security Events

Exceeded limits return:

```json
{"detail": "Too many requests. Please try again later."}
```

The response status is `429 Too Many Requests` and includes a `Retry-After` header.

Every exceeded limit creates an organization-scoped `security.rate_limited` audit event where
organization context is available. Events include the actor, request context, endpoint, scope,
`outcome=denied`, and `reason=rate_limit_exceeded`. Passwords, tokens, request bodies, Redis URLs,
and raw login identifiers are never included.

## Production Notes

- Use a dedicated Redis instance with TLS and authentication.
- Keep `REDIS_URL` only in deployment environment variables.
- Monitor `security.rate_limited` events and Redis availability.
- Tune limits using observed legitimate traffic and bank security requirements.
- Keep multiple API instances pointed at the same Redis service.
