# AgentHQ Backend Performance and Reliability Audit

Audit scope: current backend implementation, including API routes, services, repositories, models,
migrations, and production failure boundaries. This phase is audit-only; no application code was
changed.

## Executive Summary

AgentHQ is structurally clean and uses database-level filtering for most list and reporting
queries. It does not currently show widespread ORM relationship-driven N+1 behavior because the
models are queried directly without lazy-loaded response relationships.

The main production scaling risks are:

1. Every audited list endpoint returns an unbounded result set.
2. Most frequently filtered and sorted columns have no supporting database indexes.
3. Dashboard and compliance endpoints execute many sequential count queries.
4. MCP sync performs per-tool lookups and commits, producing N-per-tool database work.
5. Policy decision evaluation retrieves a broad rule set and filters/sorts it in Python.
6. Database and future external MCP operations have no explicit timeout policy.
7. Multi-step governance actions use multiple commits and compensating writes rather than a single
   atomic transaction.

At the current demo scale these issues are unlikely to be visible. At enterprise audit-log,
execution, and incident volumes, they will cause increasing latency, database load, and operational
risk.

## High Priority Findings

### 1. All Core List Endpoints Are Unbounded

The following endpoints return every matching row and also run a separate `COUNT(*)` query:

| Endpoint | Current behavior | Risk |
| --- | --- | --- |
| `GET /api/v1/agents` | Unbounded, ordered by `created_at DESC` | Large registries increase response size and memory use. |
| `GET /api/v1/agents/{agent_id}/tools` | Unbounded per agent | Tool-heavy agents may produce large payloads. |
| `GET /api/v1/mcp-servers` | Unbounded, ordered by `created_at DESC` | Lower immediate risk, but still no upper bound. |
| `GET /api/v1/policy-rules` | Unbounded, ordered by priority | Large rule sets increase response and sorting cost. |
| `GET /api/v1/approvals` | Unbounded, ordered by `requested_at DESC` | Approval history grows continuously. |
| `GET /api/v1/executions` | Unbounded, ordered by `created_at DESC` | Highest growth risk; execution records are expected to grow rapidly. |
| `GET /api/v1/incidents` | Unbounded, ordered by `created_at DESC` | Incident history grows continuously. |
| `GET /api/v1/audit-logs` | Unbounded, ordered by `created_at DESC` | Critical risk; audit logs are append-only and likely the largest table. |
| `GET /api/v1/compliance/incidents` | Unbounded, ordered by `created_at DESC` | Date filters help only when supplied. |

Recommendation:

- Add consistent `limit` and `offset` pagination first, with a conservative default such as 50 and
  a hard maximum such as 200.
- Preserve `items` and `total` for compatibility.
- Consider cursor pagination for audit logs and executions after the initial hardening release.
- Add deterministic secondary ordering by primary key when using timestamp-based pagination.

### 2. Frequently Filtered Columns Lack Database Indexes

Current non-primary-key indexes are limited to:

- Unique user email.
- Partial unique active-name indexes for agents, agent tools, policy rules, and MCP servers.

PostgreSQL does not automatically create indexes for foreign-key columns. Most operational filters,
joins, counts, and sorting columns are therefore currently exposed to sequential scans.

Recommended first-wave indexes:

| Table | Recommended index | Supports |
| --- | --- | --- |
| `agents` | Partial `(created_at DESC)` where `deleted_at IS NULL` | Agent listing. |
| `agents` | Partial `(owner, created_at DESC)` where `deleted_at IS NULL` | Agent-owner scoped listing. |
| `agents` | Partial `(status)` and `(risk_level)` where `deleted_at IS NULL` | Dashboard counts and grouped metrics. |
| `agent_tools` | Partial `(agent_id, created_at DESC)` where `deleted_at IS NULL` | Tool listing and counts. |
| `approvals` | `(agent_id, requested_at DESC)` | Agent reports and filtered lists. |
| `approvals` | `(status, requested_at DESC)` | Pending/approved/rejected counts and lists. |
| `approvals` | `(risk_level)` | Risk-level filtering. |
| `executions` | `(created_at DESC)` | Primary execution listing and date reports. |
| `executions` | `(agent_id, created_at DESC)` | Agent compliance reports and filtering. |
| `executions` | `(status, created_at DESC)` | Dashboard/compliance counts and filtered lists. |
| `executions` | `(risk_level)` | Risk filtering. |
| `executions` | `(approval_id)` and `(tool_id)` | Existing list/filter and relationship lookups. |
| `incidents` | `(created_at DESC)` | Incident and compliance listing. |
| `incidents` | `(agent_id, created_at DESC)` | Agent reports and filtering. |
| `incidents` | `(status, created_at DESC)` | Status filtering and dashboard counts. |
| `incidents` | `(severity, created_at DESC)` | Severity filtering and critical counts. |
| `incidents` | `(execution_id)` | Execution-linked incident validation/filtering. |
| `audit_logs` | `(created_at DESC)` | Audit listing and date-based compliance counts. |
| `audit_logs` | `(entity_type, entity_id, created_at DESC)` | Entity audit history. |
| `audit_logs` | `(action, created_at DESC)` | Action filtering and policy-decision counts. |
| `audit_logs` | `(actor, created_at DESC)` | Actor filtering. |
| `policy_rules` | Partial `(scope, agent_id, tool_id, is_enabled, priority)` where `deleted_at IS NULL` | Policy evaluation and filtered listing. |
| `mcp_servers` | Partial `(status)` where `deleted_at IS NULL` | Dashboard MCP counts. |
| `mcp_servers` | Partial `(agent_id)` where `deleted_at IS NULL` | Linked-agent lookups. |
| `users` | `(is_active)` only if user volume justifies it | Dashboard active-user count. |

Index additions should be validated with PostgreSQL `EXPLAIN (ANALYZE, BUFFERS)` against realistic
data before adding every proposed index. Write-heavy tables such as executions and audit logs need a
deliberate balance between read performance and index maintenance cost.

### 3. Dashboard Summary Executes 24 Sequential Queries

`GET /api/v1/dashboard/summary` currently executes approximately 24 individual aggregate queries:

- 4 agent counts.
- 6 execution counts.
- 3 approval counts.
- 4 incident counts.
- 3 MCP server counts.
- 2 user counts.
- 2 execution aggregate queries for cost and latency.

The frontend also requests three grouped dashboard endpoints separately:

- Agents by risk.
- Executions by status.
- Approvals by status.

Risk:

- Latency accumulates across sequential database round trips.
- Database pressure grows rapidly as dashboard usage increases.
- Missing indexes amplify each count query.

Recommendation:

- Consolidate status counts using conditional aggregation or grouped queries.
- Compute execution total, statuses, today's executions, cost, and latency in one query.
- Compute agent, approval, incident, MCP, and user metrics in one grouped/conditional query per
  table.
- Target roughly 6-8 database queries for the full dashboard instead of 27 across the current
  summary and grouping requests.
- Consider a short-lived cache only after query consolidation and measurement.

### 4. Compliance Aggregations Use Excessive Query Fan-Out

`GET /api/v1/compliance/summary` executes approximately 10 sequential count queries.

`GET /api/v1/compliance/agent/{agent_id}` executes approximately 10 queries:

- Agent lookup.
- Tool count.
- Policy-rule count.
- Three execution counts.
- Approval count.
- Incident count.
- Latest execution timestamp.
- Latest incident timestamp.

Recommendation:

- Consolidate compliance summary metrics by source table using conditional aggregation.
- Consolidate agent execution metrics and latest execution timestamp into one query.
- Consolidate incident count and latest incident timestamp into one query.
- Keep date and agent filters in SQL; this is already done correctly.

### 5. MCP Sync Has N-Per-Tool Queries and Commits

MCP sync performs, for every discovered tool:

1. A lookup by agent and tool name.
2. A create or update.
3. A database commit and refresh.

It can also create a linked agent and audit records in separate committed transactions.

Risk:

- Sync time grows linearly with tool count and incurs multiple network round trips per tool.
- Partial sync state is possible if a later tool operation fails.
- If the final sync audit fails, tool mutations may already be committed even though the API
  returns failure.

Recommendation:

- Load all existing tools for the agent in one query and map them by name.
- Apply all creates and description updates in one transaction.
- Commit agent creation, tool upserts, server state, and success audit atomically.
- Add an adapter-level timeout before replacing the mock adapter with real MCP networking.

### 6. Policy Evaluation Filters Too Broadly in Python

Policy evaluation queries all enabled, non-deleted rules in candidate scopes, then filters scope,
agent/tool identity, and risk threshold in Python. It also sorts matching rules in Python.

Risk:

- Every evaluation becomes slower as the global policy table grows.
- Execution creation invokes policy evaluation, so this affects a critical write path.

Recommendation:

- Push exact global/agent/tool scope matching into SQL.
- Push priority ordering into SQL.
- Represent risk severity in a queryable form or construct an allowed-risk predicate.
- Fetch only the best matching rule with `LIMIT 1`.

## Medium Priority Findings

### 1. No Explicit Database Connection or Statement Timeouts

The SQLAlchemy engine uses `pool_pre_ping=True`, which helps detect stale connections, but it does
not configure:

- Connection timeout.
- Pool checkout timeout.
- Statement timeout.
- Pool size or overflow limits.
- Connection recycling.

Recommendation:

- Add environment-configurable connection and pool timeouts.
- Configure PostgreSQL `statement_timeout` for API workloads.
- Set pool size and overflow deliberately for Render/Supabase connection limits.
- Document transaction-pooler compatibility if using Supabase pooler endpoints.

### 2. MCP Discovery Has No Timeout Boundary

The current mock adapter is immediate, but the adapter protocol has no timeout or cancellation
contract. A future real MCP client could block the synchronous API worker indefinitely.

Recommendation:

- Require a bounded discovery timeout before real network integration.
- Return a stable `502` or `504` response with a safe message.
- Preserve the current behavior of retaining the linked agent, tools, and previous successful
  `last_sync_at` on discovery failure.

### 3. Multi-Step Governance Writes Are Not Fully Atomic

Critical audit failures now return a clear `503` and some actions perform compensating writes.
However, repositories commit each mutation independently. Compensation is not equivalent to an
atomic transaction:

- Process termination between mutation and compensation can leave partial state.
- MCP tool mutations may remain after a final audit failure.
- Agent creation during MCP sync may remain after later sync failure.
- Compensation itself may fail.

Recommendation:

- Introduce a service-owned transaction boundary for critical governance actions.
- Change repository writes to `flush()` rather than `commit()` within those transactions.
- Commit the business mutation and audit record together.
- Keep compensation only as a last-resort operational fallback.

### 4. Health Endpoint Does Not Check Database Readiness

`GET /health` always returns `{"status": "ok"}` and does not verify database connectivity.

Risk:

- Render or an upstream load balancer can treat the API as healthy while PostgreSQL is unavailable.

Recommendation:

- Keep a lightweight liveness endpoint.
- Add a separate readiness endpoint that performs a bounded `SELECT 1`.
- Ensure database failures return `503` with a stable error body.

### 5. Database Failures Lack a Stable API Response

Known domain errors generally return appropriate `404`, `409`, `422`, `502`, or `503` responses.
Unexpected SQLAlchemy/database failures are not handled globally and may become generic server
errors without a stable application error code.

Recommendation:

- Add narrowly scoped handlers for database unavailability and timeout conditions.
- Return a consistent JSON structure and `503 Service Unavailable`.
- Log internal details server-side without exposing connection strings or SQL.

### 6. List Queries Always Pay for Exact Total Counts

Every list endpoint performs both a full result query and an exact `COUNT(*)`, even when a client may
only need the first page.

Recommendation:

- Preserve exact totals initially for compatibility.
- Measure count-query cost on executions and audit logs.
- Consider optional totals or cursor responses for high-volume tables later.

### 7. User List Is Also Unbounded

Although not part of the requested pagination list, `GET /api/v1/users` is also unbounded and should
follow the same pagination contract.

## Low Priority Findings

### 1. No Classic ORM N+1 in Current Read Responses

Current response serialization does not traverse ORM relationships, so list endpoints do not
currently trigger classic lazy-loading N+1 queries. This is positive.

Future relationship fields should use explicit joins or loader strategies and query-count tests.

### 2. Soft-Delete Filtering Is Mostly Consistent

Soft-deleted records are consistently excluded from:

- Agent, agent-tool, MCP-server, and policy-rule list/get operations.
- Dashboard agent and MCP counts.
- Compliance total-agent and tool/policy-rule counts.
- Policy evaluation.

Approvals, executions, incidents, audit logs, and users do not use soft deletion.

Remaining consideration:

- Historical executions, approvals, incidents, and audit records continue to count even if their
  linked agent is later soft-deleted. This may be correct for audit/compliance reporting, but the
  intended semantic should be documented explicitly.

### 3. Error Response Shape Is Mostly Consistent but Not Fully Stable

Most explicit errors use FastAPI's standard:

```json
{"detail": "Clear message."}
```

Exceptions:

- Request validation errors return `detail` as a list of structured objects.
- Unexpected server/database errors do not have a defined AgentHQ error schema.
- Errors have no stable machine-readable code, request ID, or correlation ID.
- `404`, `409`, and `422` usage is generally reasonable, but error handling is repeated in route
  handlers and may drift over time.

Recommendation:

- Introduce a small stable error envelope in a later hardening phase, for example:
  `{"code": "agent_not_found", "message": "Agent not found.", "request_id": "..."}`.
- Preserve meaningful HTTP status codes.

### 4. Authentication Token Failure Handling Is Clear

Invalid, expired, malformed, inactive-user, and unknown-user tokens consistently return `401` with a
Bearer challenge. Role failures return `403`.

Remaining considerations:

- No token revocation strategy beyond user deactivation.
- No refresh tokens.
- Default JWT secret remains unsafe if production configuration is omitted.
- Production startup should reject the default secret.

### 5. Sorting Columns Need Index Support

Most lists sort by descending timestamps or policy priority. Without supporting indexes, PostgreSQL
may sort large result sets after scanning them.

This becomes higher priority once pagination is implemented because indexed ordering is essential
for predictable page latency.

## Failure-Mode Audit

| Area | Current safety behavior | Remaining risk |
| --- | --- | --- |
| MCP discovery failure | Preserves existing agent/tools, stores error status and `last_error`, retains previous `last_sync_at`, creates failure audit, returns `502`. | No adapter timeout; failure-audit outage can prevent the intended sync error response; multi-commit sync is not atomic. |
| Policy decision during execution creation | Unexpected evaluation errors fail closed to blocked and audit the fallback. | If fallback audit fails, request returns `503`; no transaction-wide atomicity with subsequent execution audit. |
| Direct policy decision evaluation | Known errors are mapped; audit logging is critical. | Unexpected non-audit errors become generic `500` rather than a stable fallback response. |
| Critical audit logging | Critical audit failures return `503`; selected actions compensate. | Compensation is best-effort and not transactionally atomic. |
| Dashboard frontend | Widgets use independent queries and local retry states. | Backend summary itself is monolithic; one failed count causes the entire summary request to fail. |
| Auth tokens | Invalid/expired/inactive tokens return clear `401`; role failures return `403`. | Production startup does not reject the default JWT secret. |
| Database availability | `pool_pre_ping` detects stale connections. | No readiness check, explicit timeouts, stable database-error response, or pool sizing policy. |

## API Response Consistency Audit

Strengths:

- Domain errors generally have clear human-readable messages.
- HTTP status codes are mostly semantically appropriate.
- Authentication consistently distinguishes `401` from `403`.
- MCP discovery failures use `502`.
- Critical audit failures use `503`.

Gaps:

- No stable machine-readable error code.
- Validation errors have a different `detail` shape from domain errors.
- Unexpected and database errors are not normalized.
- No request/correlation ID is returned.
- Some route-specific error handling is duplicated and may drift.

## Recommended Implementation Order

1. **Add bounded pagination**
   - Start with audit logs, executions, incidents, approvals, and compliance incidents.
   - Apply the same contract to all list endpoints, including users.

2. **Add high-value indexes**
   - Prioritize audit logs, executions, incidents, approvals, foreign keys, and timestamp ordering.
   - Validate on PostgreSQL with realistic row counts and query plans.

3. **Consolidate dashboard and compliance aggregates**
   - Reduce query fan-out before adding caching.

4. **Make critical writes transactional**
   - Move commit ownership from repositories to service-level transaction boundaries.
   - Commit audit and governance mutations atomically.

5. **Optimize policy evaluation and MCP sync**
   - Select the best policy rule in SQL.
   - Batch MCP tool lookups/upserts and commit once.

6. **Add timeout and readiness controls**
   - Database connection/pool/statement timeouts.
   - MCP adapter timeout.
   - Database readiness endpoint and stable `503` responses.

7. **Standardize error envelopes and observability**
   - Machine-readable error codes, request IDs, structured logs, and latency/query metrics.

## Proposed v0.3.2 Hardening Scope

Recommended bounded scope for AgentHQ v0.3.2:

- Add `limit` and `offset` pagination with defaults and maximums to all unbounded list endpoints.
- Add the first-wave PostgreSQL indexes for executions, audit logs, incidents, approvals, agent
  tools, policy rules, MCP servers, and agent-owner listing.
- Consolidate dashboard summary query fan-out.
- Consolidate compliance summary and agent-report query fan-out.
- Push policy-rule matching and ordering into SQL with `LIMIT 1`.
- Batch MCP discovered-tool lookup and upsert work.
- Introduce service-owned atomic transactions for execution creation, approval decisions, policy
  evaluation audits, MCP sync, and user deactivation.
- Add configurable database and MCP timeouts.
- Add database readiness checking and stable database-unavailable responses.
- Add performance-focused tests:
  - Pagination boundary tests.
  - Query-count regression tests for dashboard, compliance, policy evaluation, and MCP sync.
  - Critical transaction rollback tests.
  - PostgreSQL migration/index verification.

Out of scope for v0.3.2:

- New product capabilities.
- New governance workflows.
- Caching before query consolidation and measurement.
- Premature denormalization or external analytics infrastructure.
