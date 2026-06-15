# AgentHQ Hardening Audit

## Summary

The post-v0.8 audit reviewed repository hygiene, security controls, REST and MCP gateway behavior,
AI risk and compliance services, frontend shell behavior, migrations, performance-sensitive paths,
and release documentation.

The platform remains strongly tenant-scoped and fail-closed across the reviewed governance paths.
This pass fixed four concrete regressions: migration metadata drift, unbounded gateway input
payloads, unsafe handling of non-object JSON-RPC requests, and missing rate limiting on the v0.8
risk and compliance endpoints.

## Issues Fixed

* Restored SQLAlchemy metadata for the existing `users.email` unique constraint and unique index.
  `alembic check` no longer proposes removing the production constraint.
* Added a 64 KiB limit for REST and MCP gateway tool-call input payloads.
* Added a safe JSON-RPC `Invalid Request` response for non-object MCP requests.
* Updated MCP gateway server information from stale version `0.7.0` to `0.8.0`.
* Applied the centralized compliance rate limiter to Risk Register, Compliance Controls,
  Compliance Evaluation, and Risk Summary endpoints.
* Updated current quality documentation from 354 to 357 passing tests.

## Security Checks

* No tracked `.env` files, logs, caches, dependency folders, or frontend build artifacts were
  found.
* Local `.env`, logs, caches, `node_modules`, and `frontend/dist` remain ignored.
* A tracked-file secret scan found no committed credentials or private keys. Example and test
  placeholders remain intentionally present.
* Frontend organization identifiers appear only in response types; organization-scoped request
  bodies do not send `organization_id`.
* Backend repositories and authorization helpers continue deriving organization context from the
  authenticated membership or gateway credential.
* Audit snapshots and metadata continue through centralized recursive redaction.
* Gateway credentials remain hashed at rest, returned only on create/rotation, and denied when
  revoked or expired.

## Gateway Checks

* REST and MCP protocols use the shared `call_gateway_tool` enforcement service.
* Blocked and approval-required decisions do not call the upstream MCP server.
* Approvals are validated against organization context, agent, action name, and approved status.
* Disabled, archived, soft-deleted, cross-agent, and cross-tenant access remains denied.
* Upstream execution errors are returned as stable sanitized messages.
* Input summaries and output summaries remain bounded.
* Gateway list, call, and credential operations remain rate limited and audited.
* Regression coverage now includes oversized input and non-object JSON-RPC requests.

## Risk & Compliance Checks

* Risk records, controls, snapshots, alerts, and summaries remain organization scoped.
* Risk records and daily snapshots retain database uniqueness constraints.
* Discovered-tool queries exclude soft-deleted tools, agents, and MCP servers.
* Compliance and governance alerts use idempotent active-alert reconciliation.
* Empty-workspace risk and compliance calculations remain valid.
* New v0.8 risk and compliance read endpoints now use centralized compliance abuse protection.

## Frontend UX Checks

* The application shell has one sidebar toggle, fully hides the desktop sidebar, expands content,
  and supports mobile backdrop and Escape-key closing.
* Navigation links match current protected routes and remain role aware.
* Dashboard onboarding precedes metrics for incomplete workspaces and uses role-aware actions.
* Reviewed tables use horizontal overflow containers and long JSON/identifier content uses safe
  wrapping or scrolling.
* Frontend build and lint pass without application changes in this audit.

## Migration Checks

* Alembic has one head: `202606130005`.
* `alembic check` reports no new upgrade operations.
* Recent gateway, governance, and risk tables enable RLS, revoke Supabase client roles, and include
  organization-scoped indexes.
* Migration files contain no environment-specific values.
* Existing downgrade functions follow the repository convention.

## Performance Checks

* Major operational list endpoints retain bounded pagination.
* Gateway credential lists, audit logs, governance alerts, and Risk Register API responses are
  bounded.
* Existing dashboard and compliance query-count regression tests remain green.
* Current gateway tool listing and policy enforcement avoid ORM relationship-driven N+1 loading.

## Items Intentionally Left Unchanged

* Historical release notes retain their release-specific test counts.
* Local ignored artifacts were not deleted because they are not tracked or staged.
* Approval reuse behavior remains unchanged and is documented as current gateway behavior.
* Existing public API response shapes and governance enforcement behavior remain unchanged.

## Review Later

* Reserve idempotency keys before upstream execution to prevent two simultaneous first requests
  from both reaching upstream before the unique call-record constraint resolves the race.
* Risk Register reconciliation currently materializes the organization's discovered-tool set
  before filtering and pagination. Move reconciliation and filtered paging toward database-level
  operations before very large deployments.
* Historical tenant-backfill migration `202606080004` requires an online database connection, so
  full `alembic upgrade head --sql` generation from an empty revision cannot complete.
* Invalid JSON syntax is handled by FastAPI's standard validation response before the MCP route;
  consider an MCP-specific parse-error handler if strict JSON-RPC transport conformance is needed.
* The frontend production bundle is approximately 515 kB before gzip and triggers Vite's chunk-size
  warning. Route-level code splitting is a suitable future optimization.
* Replace the deprecated Starlette `TestClient`/httpx integration when the dependency ecosystem
  provides the planned successor.

## Verification Results

* `uv run pytest -q`: 357 passed.
* `uv run ruff check .`: passed.
* `uv run mypy app tests`: passed.
* `uv run alembic heads`: one head, `202606130005`.
* `uv run alembic check`: no new upgrade operations detected.
* `npm run build`: passed; Vite emitted the documented chunk-size warning.
* `npm run lint`: passed.
* `git diff --check`: passed.
