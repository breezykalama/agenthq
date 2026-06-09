# AgentHQ v0.4.0 Code Health Audit

## Summary

The v0.4.0 repository is structurally healthy after the multi-tenant changes. The full backend
suite passes, backend repositories consistently derive tenant context, cross-resource validation
uses tenant-scoped lookups, and frontend resource requests do not send `organization_id`.

This cleanup fixed verified tenant-awareness, RBAC, type, version, and static-analysis issues
without changing public API response shapes or adding product features.

## Issues Fixed

### Tenant-Aware User Administration

* Scoped `GET /api/v1/users` to active memberships in the current organization.
* Scoped user lookup and mutation endpoints to users in the current organization.
* Prevented organization admins from reading or modifying users who only belong to another
  organization.
* Updated membership roles in the current organization when an admin changes a user's role.
* Added a tenant-isolation regression test for user administration.
* Removed the obsolete global user-list repository helper.

### Frontend RBAC Consistency

* Added one effective-role helper that prefers the current organization membership role and falls
  back to the legacy global role only when no membership is available.
* Made navigation role-aware so users do not see pages the backend will reject.
* Added role-aware route guards for MCP servers, agents, policy rules, policy decisions, approvals,
  executions, incidents, compliance, and audit logs.
* Kept invite management restricted to users with an actual admin membership.
* Updated onboarding, MCP management, and agent management to use the effective role.
* Removed the duplicated audit-specific route guard.

### Contracts, Copy, and Static Analysis

* Aligned the frontend audit-log type with the backend `organization_id` response field.
* Clarified the login page so direct registration is presented as legacy/demo access.
* Updated the FastAPI application version from `0.3.0` to `0.4.0`.
* Consolidated duplicated role-label formatting.
* Fixed two MyPy test findings without weakening type checking.

## Items Intentionally Kept

* `/api/v1/auth/register` and the `/register` page remain for legacy/demo compatibility.
* The singular `/policy-decision` frontend route remains as a compatibility alias for
  `/policy-decisions`.
* Default-organization creation and legacy global-role fallback remain for existing deployments
  and tests.
* Internal audit creation schemas still accept `organization_id`; public resource request schemas
  and frontend resource requests do not.
* Existing migrations remain unchanged.

## Items To Review Later

* User deactivation currently disables the global user identity, which affects every organization
  membership. A future organization-member deactivation contract should distinguish workspace
  access removal from global account deactivation.
* Users with multiple active memberships require an explicit organization-switching strategy.
  Current context selection intentionally supports exactly one active membership.
* The global `User.role` remains for JWT and legacy fallback compatibility even though active
  organization authorization prefers membership roles.
* Backend tests emit a Starlette deprecation warning recommending `httpx2`; dependency migration
  should be handled separately.
* The frontend currently has build and lint verification but no automated component or route-role
  test suite.

## Verification Results

* `uv run pytest`: 221 passed; one existing Starlette/httpx deprecation warning.
* `uv run ruff check .`: passed.
* `uv run mypy app tests`: passed.
* `uv run alembic heads`: one valid head, `202606080004`.
* PostgreSQL upgrade/downgrade was not run against the configured Supabase database to avoid
  modifying a live environment during a cleanup audit.
* `npm run build`: passed.
* `npm run lint`: passed.
* `git diff --check`: passed.
