# AgentHQ v0.8.2 Rollback Runbook (multi-membership compatible)

Operational procedure for rolling back the v0.8.2 organization-selection release without locking
out users who belong to more than one organization. Automated evidence:
`backend/tests/test_rollback_multi_membership_postgres.py` (PostgreSQL, opt-in).

No secrets or environment values belong in this document. Use the deployment platform's secret
store for every value referenced below.

## 1. Supported commits

| Role | Branch | Commit | Contents |
|---|---|---|---|
| Feature release candidate | `feature/v0.8.2-membership-safety` | `fc240e692707f6a4e9b4b7c8d2fd8ba5f3e638ef` | Organization-selection backend, selection frontend, invitation recovery |
| **Rollback target** | `rollback/v0.8.2-compat` | `c763f56dbcd9db357915e77884c09fa25d2c957c` | Same backend; selection frontend without invitation recovery |

* The backend application, migrations, `uv.lock` and `pyproject.toml` are **identical** in both
  commits (`git diff c763f56 fc240e6 -- backend/app backend/alembic backend/uv.lock
  backend/pyproject.toml` is empty). The only differences are frontend files and tests.
* Both run on Alembic head `202611170001`.
* Later commits on the feature branch that only add tests or documentation (such as the one that
  adds this runbook) do not change the deployable backend or frontend.

## 2. Unsafe fallback targets once multiple memberships exist

Do **not** roll back to either of these while any user has two or more active memberships
(query in section 10):

| Commit | Why |
|---|---|
| `c5d0bd3` (`release/v0.8.1-identity-hardening`) | Resolves an organization only when the user has exactly one active membership and ignores `X-AgentHQ-Organization`. Multi-membership users get `403 Organization membership required.` on every organization route. It also has no guard against creating second memberships. |
| `fa29850` (`rollback/v0.8.1-compat`) | v0.8.0 code with the v0.8.1 schema: same lockout, no second-membership guard, and none of the v0.8.1 protections (administrator email verification, trusted client IP, identity flows). |

Both fail closed (no cross-tenant data is exposed) but lock affected users out of all their
organizations; an organization whose only administrator is such a user loses administration.

## 3. Required environment

Keep the existing release configuration unchanged. Names only:

* Backend: `ENVIRONMENT=production`, `DATABASE_URL`, `JWT_SECRET_KEY` (**must be the same value**,
  or every session and undelivered email link becomes invalid), `BOOTSTRAP_SECRET`,
  `BACKEND_CORS_ORIGINS`, `FRONTEND_BASE_URL`, `REDIS_URL` (**required**: production rate limiting
  fails closed with HTTP 503 without it), the email settings (`EMAIL_BACKEND`, `EMAIL_FROM`,
  `RESEND_API_KEY` or `SMTP_*`), and `TRUSTED_CLIENT_IP_HEADER` if already configured.
* `MULTI_ORGANIZATION_MEMBERSHIPS_ENABLED`: unset or `false`. Never enable it as part of a rollback.
* Frontend: `VITE_API_BASE_URL` (embedded at build time; the rollback build must use the same API URL).

No new variable is required, and no variable needs to change.

## 4. Database and migration compatibility

1. Read the revision: `SELECT version_num FROM alembic_version;` — expect `202611170001`.
2. Confirm the rollback ships the same head:
   `git -C <rollback checkout> ls-tree -r --name-only c763f56 -- backend/alembic/versions`
   lists `202611170001_harden_identity_flows.py` as the newest revision.
3. The start command (`alembic upgrade head && uvicorn ...`) is a no-op on this database. Never run
   `alembic downgrade`. If the revision is anything other than `202611170001`, **stop** (section 12).

## 5. Identifying the exact artifacts

* Backend: the platform deployment must show commit `c763f56dbcd9db357915e77884c09fa25d2c957c`
  and the Docker image digest built from the root `Dockerfile`. `/health` does not report a
  version, so record the commit and digest from the platform's deployment details.
* Frontend: the deployment for the same commit, built with the production `VITE_API_BASE_URL`.
* Record before starting: the **current** backend and frontend deployment IDs, commits and image
  digest (the restoration targets, section 11).

Because the backend code is identical, a frontend-only rollback is sufficient when the problem is
in the frontend. Redeploy the backend only if the operator wants artifact parity.

## 6. Single-membership account

Using a dedicated test account with one membership (never a customer account):

1. `GET /health` returns `200`.
2. Sign in; `GET /api/v1/auth/me` without `X-AgentHQ-Organization` returns `200`, with
   `organization_membership` set and `organization_memberships` containing exactly one entry.
3. A route permitted to its role (for example `GET /api/v1/dashboard/summary`) returns `200`
   without a header. No `409` appears anywhere in the session.
4. In the browser: no organization picker; the header shows `<Organization> · <Role>`.

## 7. Multi-membership account

Using a test account that is Admin in organization A and Auditor in organization B:

1. `GET /api/v1/agents` without a header returns `409 {"detail": "Organization selection required."}`.
2. `GET /api/v1/auth/me` lists both memberships, with `selected_organization_id: null`.
3. With `X-AgentHQ-Organization: <A>`, `/api/v1/auth/me` shows A selected with role `admin`.
4. With `X-AgentHQ-Organization: <B>`, it shows B selected with role `auditor`.
5. In the browser: the picker lists exactly the active memberships. Choosing A shows
   `A · Admin`; switching to B shows `B · Auditor` and none of A's data on any page.

## 8. Organization-specific authorization

With the multi-membership test account:

* Header A: admin-only `GET /api/v1/organization-invites` returns `200`.
* Header B: `GET /api/v1/audit-logs` returns `200`; `GET /api/v1/organization-invites`,
  `GET /api/v1/agents` and `POST /api/v1/agents` return `403`. Admin rights in A never apply in B.
* A random UUID, or an organization the account does not belong to, returns
  `403 {"detail": "Organization access denied."}`. A deactivated membership and a deleted
  organization return the **same** response.
* A malformed, duplicated or comma-joined header returns `400 {"detail": "Invalid organization header."}`.
* An agent ID from organization B requested under header A returns `404` (read, update and delete).

## 9. Gateway and JWT verification

* A gateway token issued in organization A lists tools for A's MCP server
  (`GET /api/v1/mcp-gateway/<server-A>/tools` returns `200`) and gets `401` for B's server, with or
  without `X-AgentHQ-Organization: <B>`. Gateway tokens are scoped by their own organization; the
  user header never widens them.
* A session token issued before a password reset returns `401` (the `av` claim no longer matches
  `users.auth_version`); a fresh sign-in returns `200`.
* Existing sessions keep working across the rollback: tokens carry no organization claim, and the
  signing key is unchanged.

## 10. Data-integrity checks

Run read-only, before and after the rollback, and compare:

```sql
SELECT version_num FROM alembic_version;

-- Users with more than one active membership in non-deleted organizations.
SELECT count(*) FROM (
  SELECT m.user_id FROM organization_memberships m
  JOIN organizations o ON o.id = m.organization_id
  WHERE m.is_active AND o.deleted_at IS NULL
  GROUP BY m.user_id HAVING count(*) > 1) t;

-- Deterministic fingerprints; each must be identical before and after.
SELECT md5(coalesce(string_agg(t::text, chr(10) ORDER BY t::text), '')) FROM organization_memberships t;
SELECT md5(coalesce(string_agg(t::text, chr(10) ORDER BY t::text), '')) FROM organizations t;
SELECT md5(coalesce(string_agg(t::text, chr(10) ORDER BY t::text), '')) FROM organization_invites t;
SELECT md5(coalesce(string_agg(t::text, chr(10) ORDER BY t::text), '')) FROM users t;
```

Expected to change during verification, and not a failure: `audit_logs` (sign-ins and denials),
`mcp_gateway_tokens.last_used_at`/`updated_at` (gateway use), and `risk_snapshots` (one daily row
per organization when a dashboard is opened). `users` can change if a test account signs up or
resets its password; use pre-existing test accounts for the checks.

## 11. Restoring the previous artifact

Redeploy the deployment IDs recorded in section 5 (by commit and image digest, not by branch
name). The schema is shared, so no database step is needed in either direction. Repeat sections
6–10 afterwards.

## 12. Abort immediately if

* `alembic_version` is not `202611170001`, or startup attempts any migration.
* Any membership, organization or invitation fingerprint changes.
* Any cross-tenant read or write succeeds, or any response under one organization shows another
  organization's data.
* A multi-membership account gets `403 Organization membership required.` (old-backend lockout)
  or a single-membership account gets `409` (selection wrongly required).
* A revoked session token is accepted, or a gateway token reaches another organization.
* Authentication endpoints return `503` (rate-limit backend missing).

Abort means: restore the recorded artifacts (section 11) and escalate; do not retry with an older
build.

## 13. Fix-forward when the tenancy resolver itself is defective

The rollback cannot help with a defect in organization selection: its backend is the same code.

1. Contain: disable the affected operations (for example remove access at the edge or revoke the
   affected gateway tokens) instead of rolling back to `c5d0bd3` or `fa29850`.
2. Keep `MULTI_ORGANIZATION_MEMBERSHIPS_ENABLED` disabled.
3. Do not deactivate or delete memberships to work around the defect.
4. Reproduce with `test_organization_context.py` and
   `test_rollback_multi_membership_postgres.py`; fix on a new branch from the feature release;
   release it through the normal review, with the sections above as the acceptance checks.
5. An older backend is acceptable only if the multi-membership count (section 10) is `0`.

## Recovery limitations

* The rollback candidate **shares the organization-selection backend** with the feature release
  (`dd8dd99`). It is a rollback for the frontend and for later changes, not for the tenancy
  backend.
* `MULTI_ORGANIZATION_MEMBERSHIPS_ENABLED=false` only stops **new** second memberships at
  invitation acceptance (`409 Multiple organizations are not yet supported.`, invitation stays
  pending). It does not revoke, deactivate or hide existing memberships, and organization
  selection keeps working for them.
* Older rollback builds (`c5d0bd3`, `fa29850`) lock out users who already have multiple
  memberships.
* A tenant-isolation defect may require disabling affected operations and a controlled
  fix-forward release (section 13).
* Not covered by the committed test suite: real-browser behavior (exercised only by the local
  rollback rehearsal's browser script), the hosting platforms' build and deploy steps, and rate
  limiting against a live Redis (only the fail-closed path without Redis is tested). The rollback
  tests run in development mode with in-memory rate limiting, and provision organizations B–D
  directly because no API creates a second organization.
