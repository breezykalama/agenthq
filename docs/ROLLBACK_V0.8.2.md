# AgentHQ v0.8.2 Rollback Runbook (security-compatible)

Operational procedure for recovering from a faulty v0.8.2 release without weakening the identity,
tenancy and gateway protections it introduced, and without locking out users who belong to more
than one organization.

Automated evidence: `backend/tests/test_rollback_multi_membership_postgres.py`,
`backend/tests/test_gateway_organization_state.py`, `backend/tests/test_no_implicit_membership.py`
and `backend/tests/test_registration_defaults.py` (PostgreSQL tests are opt-in). A local
release → rollback → roll-forward rehearsal is recorded in section 16.

This runbook does not authorize any deployment. Every rollback, roll-forward or configuration
change still needs the normal release approval. No secrets or environment values belong in this
document; use the deployment platform's secret store for every value referenced below.

**This copy, in the release commit `cd43d1f`, is authoritative.** The rollback branches carry
older copies of this file (`c7ed2e8` has the earlier `e53f81e` version, which lacks the
corrections in this one). Never follow the runbook from a rollback checkout.

## 1. Commits

| Role | Branch | Commit | Use |
|---|---|---|---|
| Secured release | `feature/v0.8.2-membership-safety` | `cd43d1f5ce18ca83f93d84694315459b5ef0fc8e` | The release being recovered from or rolled forward to |
| **Primary rollback** | `rollback/v0.8.2-security-compat` | `c7ed2e8a347238e8ba428f74244c2e56a1cd6913` | Frontend recovery (section 2) |
| Conditional, exceptional | `rollback/v0.8.2-compat` | `c763f56dbcd9db357915e77884c09fa25d2c957c` | Older backend, only after every section 12 precheck passes |
| Pre-release staging baseline; restricted | `release/v0.8.1-identity-hardening` | `c5d0bd359634444dfadea8a6cd1b8026ab304c60` | Only after every section 12.6 check passes; never automatically (sections 3, 13, 14) |
| Never after multiple memberships exist; restricted | `rollback/v0.8.1-compat` | `fa29850b67c6c1378b4240e46e34dab399450391` | See section 3 |

The release `cd43d1f` has the same application as `e53f81e`: the two differ only in this runbook
and in `tools/browser-regression/`, which are not part of either build. Verify (prints nothing):
`git diff e53f81e cd43d1f -- backend frontend Dockerfile render.yaml docker-compose.yml`.

The primary rollback `c7ed2e8` is the secured release with only `frontend/` restored from `c763f56`:

* `backend/` (application, migrations, `pyproject.toml`, `uv.lock`), `docs/`, the Dockerfiles,
  `render.yaml`, `docker-compose.yml` and every frontend build file (`package.json`,
  `package-lock.json`, `vite.config.ts`, `vercel.json`) are **byte-identical** to `e53f81e`. It
  therefore keeps every backend protection of the release (section 10).
* `frontend/` is byte-identical to `c763f56`, the frontend rehearsed in the first rollback
  rehearsal and again in section 16.
* Verify before use (each command prints nothing when the trees match):
  `git diff cd43d1f c7ed2e8 -- . ':(exclude)frontend' ':(exclude)docs' ':(exclude)tools'`,
  `git diff e53f81e c7ed2e8 -- . ':(exclude)frontend'` and `git diff c763f56 c7ed2e8 -- frontend`.

**It is a frontend recovery artifact.** Its backend is the release backend, so it cannot repair any
defect in backend code shared with the release (organization selection, membership authorization,
gateway authentication, invitations, bootstrap). Those require a fix-forward (section 15).

`c763f56` contains the same organization-selection backend (`dd8dd99`) but lacks three later
backend protections: refusing gateway credentials of deleted organizations, the removal of the
implicit (legacy) membership fallback, and registration being disabled by default. It is
acceptable only under the conditions in section 12.

## 2. Recovery decision matrix

| # | Situation | Action | Primary rollback `c7ed2e8`? | Older backend `c763f56`? |
|---|---|---|---|---|
| 1 | Frontend regression | Keep the release backend; deploy the `c7ed2e8` frontend (or redeploy a recorded earlier frontend deployment of `c763f56`) | **Yes** (frontend only) | Not needed |
| 2 | Backend fails to start | Check configuration first (section 4: `REDIS_URL`, secrets, `DATABASE_URL`). A code fault cannot be cured by `c7ed2e8` (same backend) | No (identical backend) | Exceptional only, if section 12 passes; otherwise fix-forward |
| 3 | Organization-selection defect | Fix-forward (section 15). The selection code is shared by every candidate | No | No |
| 4 | Membership-authorization defect | Fix-forward. If the defect is confined to the post-`c763f56` change (implicit-membership removal), `c763f56` behaves the same for real members | No | Exceptional only, if section 12 passes |
| 5 | Gateway-authentication defect (for example active organizations refused) | Fix-forward; or contain by revoking the affected tokens | No | Exceptional only if the deleted-organization token check (section 12.4) is 0 |
| 6 | Invitation acceptance failing | Backend: fix-forward. Frontend presentation only: frontend rollback | Frontend issues only | Exceptional only, if section 12 passes |
| 7 | Bootstrap failing | Backend bootstrap code is unchanged since `c763f56` apart from defaults. Frontend: the `c7ed2e8` frontend offers the older `/?auth=bootstrap` dialog, which sends the bootstrap secret | Frontend issues only | Rarely needed |
| 8 | Redis unavailable | Restore Redis. Every build fails closed (HTTP 503) on rate-limited endpoints without it; a rollback does not help. Disabling rate limits is a separate, explicitly approved operator decision | No | No |
| 9 | Database migration incompatibility | Not possible for this release: every listed commit runs on `202611170001`. A future migration-bearing release needs its own compatibility artifact (section 17). Never downgrade | n/a | n/a |
| 10 | Mismatched frontend and backend | Safe: older frontend with the release backend (the backend enforces everything; section 18 lists the UI differences). Unsafe: any frontend with a pre-release backend unless section 12 passes | Yes | Only with section 12 |

Abort any recovery that meets a section 14 condition. Where the security effect of a recovery is
uncertain, do not roll back the backend: contain and fix forward.

## 3. Restricted older builds (`c5d0bd3`, `fa29850`)

Returning to either build restores older security behaviour. Neither is ever restored
automatically, including by an abort (section 14). A multi-membership count of `0` is
**necessary but not sufficient**: `c5d0bd3` additionally requires every section 12.6 check, and
`fa29850` is not a recovery candidate for this release.

Do **not** use either of these while any user has two or more active memberships (section 11
query):

| Commit | Why |
|---|---|
| `c5d0bd3` (`release/v0.8.1-identity-hardening`) | Resolves an organization only when the user has exactly one active membership and ignores `X-AgentHQ-Organization`. Multi-membership users get `403 Organization membership required.` on every organization route. It also has no guard against creating second memberships. |
| `fa29850` (`rollback/v0.8.1-compat`) | v0.8.0 code with the v0.8.1 schema: same lockout, no second-membership guard, and none of the v0.8.1 protections (administrator email verification, trusted client IP, identity flows). |

Both fail closed (no cross-tenant data is exposed) but lock affected users out of all their
organizations; an organization whose only administrator is such a user loses administration.
Neither contains the protections listed in section 10.

## 4. Required environment

Keep the existing release configuration unchanged. Names only:

* Backend: `ENVIRONMENT=production`, `DATABASE_URL`, `JWT_SECRET_KEY` (**must be the same value**,
  or every session and undelivered email link becomes invalid), `BOOTSTRAP_SECRET`,
  `BACKEND_CORS_ORIGINS`, `FRONTEND_BASE_URL`, `REDIS_URL` (**required**: production rate limiting
  fails closed with HTTP 503 without it), the email settings (`EMAIL_BACKEND`, `EMAIL_FROM`,
  `RESEND_API_KEY` or `SMTP_*`), and `TRUSTED_CLIENT_IP_HEADER` if already configured.
* `ALLOW_PUBLIC_REGISTRATION`: the release disables registration unless this is explicitly `true`.
  Keep it unset or `false`. It **must be explicitly `false`** before any exceptional older-backend
  rollback (section 12.3).
* `MULTI_ORGANIZATION_MEMBERSHIPS_ENABLED`: unset or `false`. Never enable it as part of a rollback.
* Frontend: `VITE_API_BASE_URL` (embedded at build time; the rollback build must use the same API URL).

The primary rollback needs no new variable and no variable change.

## 5. Database and migration compatibility

1. Read the revision: `SELECT version_num FROM alembic_version;` — expect `202611170001`.
2. Confirm the rollback ships the same head:
   `git ls-tree -r --name-only c7ed2e8 -- backend/alembic/versions` lists
   `202611170001_harden_identity_flows.py` as the newest revision (the same holds for `c763f56`).
3. The start command (`alembic upgrade head && uvicorn ...`) is a no-op on this database. Never run
   `alembic downgrade`. If the revision is anything other than `202611170001`, **stop** (section 14).

## 6. Identifying the exact artifacts

* Primary rollback: the frontend deployment must show commit
  `c7ed2e8a347238e8ba428f74244c2e56a1cd6913` (or a recorded earlier deployment of `c763f56`),
  built with the production `VITE_API_BASE_URL`. The backend stays on the release (`cd43d1f`).
* If the backend is redeployed for artifact parity, its deployment must show `c7ed2e8` and the
  Docker image digest built from the root `Dockerfile`; the code is identical to the release.
* `/health` does not report a version: record commits and image digests from the platform's
  deployment details.
* Record before starting: the **current** backend and frontend deployment IDs, commits and image
  digest (the restoration targets, section 13).

## 7. Single-membership account

Using a dedicated test account with one membership (never a customer account):

1. `GET /health` returns `200`.
2. Sign in; `GET /api/v1/auth/me` without `X-AgentHQ-Organization` returns `200`, with
   `organization_membership` set and `organization_memberships` containing exactly one entry.
3. A route permitted to its role (for example `GET /api/v1/dashboard/summary`) returns `200`
   without a header. No `409` appears anywhere in the session.
4. In the browser: no organization picker; the header shows `<Organization> · <Role>`.

## 8. Multi-membership account

Using a test account that is Admin in organization A and Auditor in organization B:

1. `GET /api/v1/agents` without a header returns `409 {"detail": "Organization selection required."}`.
2. `GET /api/v1/auth/me` lists both memberships, with `selected_organization_id: null`.
3. With `X-AgentHQ-Organization: <A>`, `/api/v1/auth/me` shows A selected with role `admin`.
4. With `X-AgentHQ-Organization: <B>`, it shows B selected with role `auditor`.
5. In the browser: the picker lists exactly the active memberships. Choosing A shows
   `A · Admin`; switching to B shows `B · Auditor` and none of A's data on any page.

## 9. Organization-specific authorization

With the multi-membership test account:

* Header A: admin-only `GET /api/v1/organization-invites` returns `200`.
* Header B: `GET /api/v1/audit-logs` returns `200`; `GET /api/v1/organization-invites`,
  `GET /api/v1/agents` and `POST /api/v1/agents` return `403`. Admin rights in A never apply in B.
* A random UUID, or an organization the account does not belong to, returns
  `403 {"detail": "Organization access denied."}`. A deactivated membership and a deleted
  organization return the **same** response.
* A malformed, duplicated or comma-joined header returns `400 {"detail": "Invalid organization header."}`.
* An agent ID from organization B requested under header A returns `404` (read, update and delete).

## 10. Security invariants (gateway, identity, onboarding)

Each must hold on the release and on the primary rollback (they share the backend):

* **Gateway scope:** a gateway token issued in organization A lists tools for A's MCP server
  (`GET /api/v1/mcp-gateway/<server-A>/tools` returns `200`) and gets `401` for B's server, with or
  without `X-AgentHQ-Organization: <B>`. The user header never widens a gateway token.
* **Deleted organizations:** a token whose organization is soft-deleted gets `401` with the same
  body as an unknown token (`{"detail": "Invalid gateway token."}`); it is never marked used.
* **Revoked and expired credentials:** a revoked gateway token and an expired one each get `401`.
* **JWT revocation:** a session token issued before a password reset gets `401` (its `av` claim no
  longer matches `users.auth_version`); a fresh sign-in gets `200`. Existing sessions keep working
  across the rollback: tokens carry no organization claim, and the signing key is unchanged.
* **Single-use invitations:** replaying an accepted invitation gets
  `400 {"detail": "Invite is invalid or expired."}`, identical with the correct or a wrong password.
* **Registration disabled:** `POST /api/v1/auth/register` gets `403` with the same body for a new
  and for an existing email address. (Do not run this probe if registration might be enabled: it
  would create an account. Read the setting instead, section 12.3.)
* **No implicit membership:** an account without an active membership gets
  `403 {"detail": "Organization membership required."}` on organization routes, and no membership
  row appears (section 11 fingerprint). Its global `users.role` grants nothing.
* **Tenant roles and isolation:** sections 8 and 9.
* **Bootstrap:** on an initialized installation `POST /api/v1/organizations/bootstrap` gets
  `409 {"detail": "An active organization already exists."}` whatever the bootstrap secret (the
  check precedes secret validation). On a fresh installation a missing or wrong secret gets
  `403 {"detail": "Bootstrap authorization failed."}` and creates no user or membership.
* **Flags:** `MULTI_ORGANIZATION_MEMBERSHIPS_ENABLED` is unset or `false`; a second-membership
  invitation acceptance gets `409 {"detail": "Multiple organizations are not yet supported."}` and
  the invitation stays pending.

## 11. Data-integrity checks

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
per organization when a dashboard is opened). `users`, `organization_memberships` and
`organization_invites` change only through a deliberate, recorded action (for example accepting a
test invitation); any other change is unexplained and blocks the recovery. Use pre-existing test
accounts for the checks.

## 12. Exceptional rollback to the older backend (`c763f56`)

Use only when the release backend itself must be replaced and a fix-forward is not possible in
time. **Every check below must pass, with recorded evidence, a documented recovery reason and
explicit authorization by an accountable operator.** If any result is uncertain, abort and fix
forward.

### 12.1 Multi-membership compatibility

Run the section 11 multi-membership query and record the count. `c763f56` resolves these users
(it has the same organization-selection backend as the release), so a non-zero count does not by
itself block `c763f56`; it does block every older build (section 3). Repeat sections 7–9 after
the rollback.

### 12.2 Legacy implicit-membership fallback

In `c763f56`, outside production only, an organization request by an account without an active
membership **creates a membership with the account's global role** when all of these hold: at
most one organization is active; either the active organization is `default-organization`, or
no organization is active and the `default-organization` placeholder was never retired (the
backend then creates it); and the account has no membership row (active or not) in that
organization. In production the fallback never runs.

```sql
SELECT
  count(*) FILTER (WHERE deleted_at IS NULL)                                   AS active_organizations,
  count(*) FILTER (WHERE deleted_at IS NULL AND slug = 'default-organization') AS active_default_organization,
  count(*) FILTER (WHERE deleted_at IS NOT NULL AND slug = 'default-organization') AS retired_placeholder
FROM organizations;
```

* `ENVIRONMENT=production`, confirmed through an authorized read of the platform's service settings
  and recorded (who, when): the fallback code path is disabled. This is the only state in which
  12.2 passes on its own.
* Any other environment value, or an unconfirmed one: **treat the environment as unsafe.** The
  fallback is enabled in that code, and the query above only shows whether its organization
  preconditions hold at the moment it runs. It is not proof that any user is safe: if the
  organization state changes during the rollback (for example an organization is soft-deleted, or
  the placeholder state changes), the fallback can start creating admin-role memberships.
  Proceed only with an explicit, independently verified mitigation that keeps the preconditions
  false for the whole rollback window (for example a recorded freeze on organization changes,
  verified by a second operator), and re-run the query before and after the rollback.
* The rollback is **blocked** whenever the query shows the preconditions true:
  `active_organizations <= 1` and either `active_default_organization = 1`, or
  `active_organizations = 0 AND retired_placeholder = 0`. (An active `default-organization`
  alongside one or more other active organizations does not enable the fallback; that is a
  precondition detail, not a mitigation.)

### 12.3 Public registration

`c763f56` enables registration by default outside production, and attaches registrants to a sole
`default-organization`. Require `ALLOW_PUBLIC_REGISTRATION=false` **set explicitly** on the backend
service before the rollback, in every environment; do not rely on environment defaults. Confirm the
value through an authorized read of the platform's service settings and record who checked it and
when. Do not probe by registering an account.

### 12.4 Gateway credentials of deleted organizations

`c763f56` authenticates a gateway token without checking its organization. Block the rollback if
any active, unexpired token belongs to a soft-deleted organization:

```sql
SELECT count(*)
FROM mcp_gateway_tokens t
JOIN organizations o ON o.id = t.organization_id
WHERE o.deleted_at IS NOT NULL
  AND t.status = 'active'
  AND (t.expires_at IS NULL OR t.expires_at > now());
```

The count must be `0`. Status, revocation and expiry are separate: a token with
`status = 'revoked'` is refused by every build; a token past `expires_at` is refused by every
build; only an `active`, unexpired token of a deleted organization is accepted by `c763f56`. Do
not revoke tokens solely to pass this check without an approved containment decision.

### 12.5 Evidence and authorization

Record, before deploying `c763f56`: the results of 12.1–12.4 with timestamps, the verified
`ENVIRONMENT` and `ALLOW_PUBLIC_REGISTRATION` values (who checked, when, how), any 12.2
mitigation and its verifier, the reason the release backend cannot stay, why a fix-forward is not
possible in time, and the authorizing operator. **Missing, incomplete or uncertain evidence aborts
the procedure.** After the rollback, run sections 7–11 and repeat 12.2–12.4; any change aborts the
rollback (section 14).

### 12.6 Restoring the pre-release staging backend (`c5d0bd3`)

`c5d0bd3` is the backend deployed before this release. Restoring it brings back older security
behaviour: it lacks organization selection, the second-membership guard and invite-lockout fix,
recovery of uncertain invitation acceptance, the deleted-organization gateway check, the removal
of the implicit-membership fallback, and registration disabled by default (outside production it
is open by default, the first registrant becomes an administrator, and registrants join a sole
`default-organization`). Its frontend also ships production dependencies with known advisories
(`axios` 1.17.0, `react-router-dom` 7.17.0 and transitive packages), fixed in `c763f56`.

Prefer, in order: the primary rollback (frontend faults), containment and fix-forward (backend
faults), then `c763f56` under 12.1–12.5. Restore `c5d0bd3` only when none of these is possible,
and only when **every** check below passes, measured immediately before the change, with the
evidence and authorization required by 12.5:

1. The section 11 multi-membership count is `0`.
2. No pending, unexpired invitation would give an existing member a second organization
   (`c5d0bd3` has no guard, and accepting one locks that user out). The count must be `0`:
   ```sql
   SELECT count(*) FROM organization_invites i JOIN users u ON lower(u.email) = lower(i.email)
   WHERE i.status = 'pending' AND i.expires_at > now() AND EXISTS (
     SELECT 1 FROM organization_memberships m JOIN organizations o ON o.id = m.organization_id
     WHERE m.user_id = u.id AND m.is_active AND o.deleted_at IS NULL
       AND m.organization_id <> i.organization_id);
   ```
3. `ENVIRONMENT=production`, confirmed as in 12.2 (otherwise the fallback and default-open
   registration return).
4. `ALLOW_PUBLIC_REGISTRATION=false` set explicitly, confirmed as in 12.3.
5. The 12.2 fallback preconditions are false, with a recorded freeze on organization changes for
   the whole window.
6. The 12.4 deleted-organization token count is `0`.
7. A recorded frontend decision: the `c5d0bd3` frontend (known dependency advisories) or the
   patched `c7ed2e8` frontend (never run against the `c5d0bd3` backend).
8. `alembic_version` is `202611170001`, `JWT_SECRET_KEY` is unchanged and `REDIS_URL` is present.

After the change, run sections 7–11 and repeat checks 1–6; any change aborts it.

## 13. Restoring the previous artifact

Redeploy the deployment IDs recorded in section 6 (by commit and image digest, not by branch
name). The schema is shared, so no database step is needed in either direction. Repeat sections
7–11 afterwards.

**When the recorded previous backend is `c5d0bd3`** (the first v0.8.2 deployment over the v0.8.1
staging baseline), restoring it is not automatic: it is allowed only after every section 12.6 check
passes. Otherwise keep the release backend, contain, and fix forward (section 15). A recorded
frontend deployment may be restored freely only if it is the release or `c7ed2e8`/`c763f56`
frontend; restoring the `c5d0bd3` frontend is part of the 12.6 decision.

## 14. Abort immediately if

* `alembic_version` is not `202611170001`, or startup attempts any migration.
* Any membership, organization or invitation fingerprint changes without a recorded deliberate
  action.
* Any cross-tenant read or write succeeds, or any response under one organization shows another
  organization's data.
* A multi-membership account gets `403 Organization membership required.` (old-backend lockout)
  or a single-membership account gets `409` (selection wrongly required).
* A revoked session token is accepted, a gateway token reaches another organization, a revoked or
  expired gateway token is accepted, or a deleted organization's token is accepted.
* Registration is accepted, or an account without membership gains access or a membership.
* Authentication endpoints return `503` (rate-limit backend missing).
* An older backend is selected without the recorded section 12 evidence, or any section 12 check
  fails.

Abort means: stop the change, escalate, and restore the recorded artifacts under section 13. An
abort never restores `c5d0bd3` or `fa29850` by itself: if the recorded backend is `c5d0bd3`,
section 12.6 applies; if it fails, keep the release backend, contain and fix forward. Do not retry
with an older build.

## 15. Fix-forward when shared backend code is defective

No rollback helps with a defect in backend code shared by the release and the rollback
candidates: organization selection, membership authorization, gateway authentication, invitations
or bootstrap.

1. Contain: disable the affected operations (for example remove access at the edge or revoke the
   affected gateway tokens) instead of rolling back to `c5d0bd3` or `fa29850`.
2. Keep `MULTI_ORGANIZATION_MEMBERSHIPS_ENABLED` disabled and `ALLOW_PUBLIC_REGISTRATION` unset or
   `false`.
3. Do not deactivate or delete memberships to work around the defect.
4. Reproduce with the tests listed at the top; fix on a new branch from the secured release;
   release it through the normal review, with sections 7–11 as the acceptance checks.
5. `c763f56` is acceptable only under sections 12.1–12.5 and `c5d0bd3` only under section 12.6.
   A multi-membership count of `0` is never sufficient on its own. `fa29850` is not a recovery
   candidate for this release.

## 16. Rehearsal evidence (local only)

A local rehearsal ran release `e53f81e` → primary rollback `c7ed2e8` → roll-forward to `e53f81e`
on one disposable PostgreSQL 18 database with a disposable Redis, in production mode with
`MULTI_ORGANIZATION_MEMBERSHIPS_ENABLED=false` (it was enabled only while seeding existing dual
memberships). A negative control ran `c763f56` against a **separate** disposable database. This is
not a hosted-deployment or production validation.

| Phase | Result |
|---|---|
| Setup through the real APIs (bootstrap, invitations, gateway tokens, password reset) | 16/16 |
| Release backend `e53f81e` | 21/21 |
| Fresh-install bootstrap (wrong or missing secret → identical `403`, nothing created) | 4/4 |
| Primary rollback backend `c7ed2e8` | 21/21 |
| Roll-forward backend `e53f81e` | 21/21 |
| Negative control `c763f56` (development, separate database) | 9/9 |
| Core browser scenarios (picker, switching, roles, cache isolation, organization header) | 16/16 on the release, the rollback and the roll-forward; on the release the first run was 15/16 because of a B12 harness race (since fixed; section 16.1), and the two reruns were 16/16 |
| Additional rollback browser workflows | passed: session survives the transition; legacy registration form receives `403`; older bootstrap dialog sends the secret only in `X-Bootstrap-Secret` and receives `409`; invitation acceptance on the older frontend |

* Alembic stayed at `202611170001`; every startup was a no-op.
* Data: 16 of 22 tables unchanged end to end. The only business-data change was one deliberate
  invitation acceptance in the browser test (one user, one membership, one invitation
  pending → accepted). Other changes were audit rows, gateway `last_used_at`/`updated_at` and two
  risk snapshots. No unexplained change.
* The negative control showed `c763f56` accepting a deleted organization's token, registration
  open with the setting unset, the fallback creating an admin membership for an account without
  one, and a registrant attached to `default-organization`; the section 12 checks flagged it.
* All containers, worktrees and generated credentials were removed afterwards.

### 16.1 Release-candidate evidence for `cd43d1f` (local only)

Disposable PostgreSQL 18 and Redis, production mode, `MULTI_ORGANIZATION_MEMBERSHIPS_ENABLED=false`.
Not a hosted-deployment or production validation.

| Check | Release `cd43d1f` | Primary rollback `c7ed2e8` |
|---|---|---|
| Browser harness, all scenarios, 10 iterations each | 19/19 | 19/19 |
| B12 (switch back to the previous organization), including negative control | 4 scenarios, 10/10 each | 4 scenarios, 10/10 each |
| B5/B9 (first selection and switch; issuance-ordered request boundaries), including two negative controls | 5 scenarios, 10/10 each | 5 scenarios, 10/10 each |
| Dashboard rendering and query-cache isolation (`dash-normal`, `dash-stale`, `dash-wrong-header`, `dash-negative`) | 4 scenarios, 10/10 each | 4 scenarios, 10/10 each |
| Core browser suite | 3 × 16/16 | 3 × 16/16 |
| Backend test suite, PostgreSQL tests included | 664 passed, 0 failed, 0 skipped | same backend |
| Frontend unit tests | 93/93 | not run |

The dashboard checks compare the rendered Total Agents card and Agents by Risk list, in every
recorded frame and after each switch, and the live query cache, against each organization's
distinct seeded values (17 and 3 agents). Their negative controls (a substituted response, a
request with the wrong header) were detected on every run.

## 17. Future migrations

* The current schema head is `202611170001`; this rollback needs no migration.
* The planned email-first signup work adds migrations. The first migration-bearing release is a
  new rollback-compatibility boundary: earlier builds cannot start against a newer revision
  (`alembic upgrade head` fails on an unknown revision), so that release needs its own newly built
  and rehearsed compatible recovery artifact before it ships.
* Production Alembic downgrades remain prohibited.

## 18. User-interface differences of the primary rollback

The `c7ed2e8` frontend is the older `c763f56` frontend. Expected differences, none of which
weakens the backend:

* Legacy registration links and form are visible again; the backend still refuses registration
  (`403`), which this frontend shows as the generic "You do not have permission to access this
  resource."
* The older "Create organization" entry points and the `/?auth=bootstrap` landing dialog return;
  `/bootstrap` has no secret field there, so production first-install setup uses the dialog. The
  backend still allows bootstrap only before the first organization and only with the secret.
* There is no recovery screen for an invitation whose response was lost; the user signs in
  normally or retries.

## 19. Open issues

* **Browser coverage limits.** Browser checks do not establish full tenant isolation; backend
  authorization is covered by the backend test suite. Numeric rendering is checked for two
  dashboard fields only; other pages rely on name-based text checks. Late-response delivery is
  forced for one endpoint and one timing. A substituted backend response is rendered as-is (the
  payloads carry no organization identifier), so backend authorization is the control. One
  dual-membership user, Chrome on Windows, local services only; B2 and B15 still use a
  request-count boundary. See `tools/browser-regression/README.md`.
* The bootstrap page's success message is not shown (the organization change remounts the page
  and the user lands on the dashboard).
* Not covered by the committed test suite: real-browser behavior (exercised only by local
  rehearsals), the hosting platforms' build and deploy steps, and rate limiting against a live
  Redis (only the fail-closed path without Redis is tested in the suite). The committed PostgreSQL
  rollback tests run in development mode with in-memory rate limiting and provision additional
  organizations directly because no API creates a second organization.

## Recovery limitations

* The primary rollback shares the release backend: it recovers frontend regressions, not backend
  defects.
* `MULTI_ORGANIZATION_MEMBERSHIPS_ENABLED=false` only stops **new** second memberships at
  invitation acceptance. It does not revoke, deactivate or hide existing memberships, and
  organization selection keeps working for them.
* `c763f56` lacks three backend protections and is usable only under section 12; `c5d0bd3` and
  `fa29850` lock out multi-membership users and lack all of them.
* A tenant-isolation defect may require disabling affected operations and a controlled
  fix-forward release (section 15).
