# AgentHQ Audit Logging

## Purpose

AgentHQ maintains an append-only, organization-scoped audit trail for governance actions, security
decisions, and sensitive report access. FastAPI is the authorization boundary; clients cannot write
audit records directly.

## Event Schema

Every new audit event records available trusted context:

| Field | Purpose |
| --- | --- |
| `event_id` / `id` | Unique event identifier |
| `timestamp` / `created_at` | Event creation time |
| `organization_id` | Trusted organization scope |
| `actor_user_id` | Authenticated AgentHQ user ID |
| `actor_role` | Active organization membership role |
| `actor` | Human-readable legacy actor label |
| `action` | Stable event action |
| `resource_type` / `entity_type` | Resource category |
| `resource_id` / `entity_id` | Resource identifier |
| `outcome` | `success`, `denied`, or `failed` |
| `reason` | Safe, bounded explanation |
| `request_id` | Request correlation identifier |
| `ip_address` | Request source address where available |
| `user_agent` | Bounded client user-agent value |
| `metadata` | Redacted operational metadata |
| `before` / `after` | Redacted governance snapshots |

Legacy names remain available for API compatibility.

## What Is Logged

- Login success and failure, plus authentication rate limiting.
- Organization bootstrap, membership creation and changes, and invite lifecycle events.
- Agent, tool, MCP server, and policy lifecycle events.
- Approval requests and decisions, including invalid decision attempts.
- Execution creation, start, completion, failure, and other updates.
- Incident creation, updates, resolution, and dismissal.
- Policy decisions and MCP sync success/failure.
- Compliance summary, agent report, and incident report access.
- Denied permissions, inactive membership access, and scoped resource misses that may represent
  cross-organization access attempts.

## Access and Tenant Isolation

- Only organization `admin` and `auditor` memberships can read audit logs.
- Audit-log reads always require an active membership and filter by the trusted organization ID.
- There are no audit update or delete API routes.
- ORM update and delete operations on `AuditLog` raise an error.
- Supabase RLS and revoked Data API grants provide an additional database boundary.

## Privacy and Security Exclusions

Audit snapshots and metadata are centrally redacted before storage. AgentHQ does not intentionally
store passwords, password hashes, JWTs, access or refresh tokens, invite tokens, token hashes,
bootstrap secrets, API keys, authorization headers, database URLs, credential-bearing URLs, or raw
credentials.

Denied cross-organization events are stored under the caller's organization and do not reveal the
target organization's identity or payload.

## Retention Considerations

Audit records should be retained according to the organization's legal, regulatory, and operational
requirements. Production deployments should define:

- Retention duration and archival storage.
- Access review and export controls.
- Monitoring for repeated denied or failed events.
- Backup, restore, and integrity-verification procedures.
- A future database-level append-only or cryptographic integrity mechanism if required by policy.

AgentHQ currently provides application-level append-only enforcement. Database owners and service
roles remain privileged operational identities and must be tightly controlled.
