# AgentHQ v0.4.0 Security Audit

## Remediation Status

This document preserves the original v0.4.0 audit findings. The following findings have since been
remediated in the v0.4.1 hardening work:

* Production rejects missing, default, short, and obviously weak JWT secrets.
* Production bootstrap requires `BOOTSTRAP_SECRET`.
* Public registration is disabled by default in production.
* Centralized rate limiting protects authentication and sensitive governance operations.
* MCP linked-agent references are tenant-validated.
* Organization admins manage membership role/status instead of global identity.
* The last active organization admin cannot be demoted or deactivated.
* Auditors have read-only incident access.
* Audit snapshots and metadata use centralized recursive secret redaction.
* MCP URLs reject credentials and unsafe production network targets.
* MCP failures return sanitized public errors.
* High-risk free-text fields have bounded lengths.
* Supabase public-schema RLS is locked down as database defense in depth.
* Audit logs are append-only, organization-scoped, and include security event trails.

Remaining recommendations should be evaluated against the current code before implementation.

## Executive Summary

AgentHQ v0.4.0 has a solid application-level tenant-isolation foundation. Core repositories derive
organization context from authenticated memberships, cross-resource validations generally use
tenant-scoped lookups, audit/dashboard/compliance reads are organization-scoped, passwords use
Argon2, invite tokens are cryptographically strong and stored only as hashes, and frontend route
guards mirror backend RBAC for the main workflows.

The audit found two critical deployment risks:

1. Production accepts a known fallback JWT secret when `JWT_SECRET_KEY` is absent.
2. An unauthenticated first caller can claim a fresh deployment through public registration or
   organization bootstrap.

No committed private key, JWT, Supabase project URL, or local `.env` file was detected. Frontend
and backend dependency advisory scans found no known vulnerabilities.

## Critical Findings

### 1. Production Does Not Reject the Default JWT Secret

`Settings.jwt_secret_key` defaults to the source-controlled value
`change-me-in-production-at-least-32-bytes`. Startup does not reject this value when
`ENVIRONMENT=production`.

Impact:

* If Render or another deployment omits `JWT_SECRET_KEY`, attackers can forge tokens for any known
  user ID.
* Forged tokens can lead to admin authorization and cross-tenant data access because the API trusts
  the signed subject before loading the user and membership.

Recommendation:

* Make `JWT_SECRET_KEY` required in production.
* Reject known defaults and secrets below a strong minimum entropy/length threshold at startup.
* Add a production-configuration test.

### 2. Fresh Deployments Can Be Claimed by an Unauthenticated Caller

Both `/api/v1/auth/register` and `/api/v1/organizations/bootstrap` are public. On an empty database,
the first direct registration becomes a global admin and can create the default organization.
Bootstrap creates the first organization admin for the first caller.

Impact:

* A newly deployed public instance can be taken over before the intended administrator completes
  setup.
* The attacker receives a valid JWT and administrator access.

Recommendation:

* Require a one-time deployment bootstrap secret or an out-of-band setup command.
* Disable public bootstrap after initialization.
* Disable or explicitly gate legacy public registration in production.

## High Priority Findings

### 1. Authentication and Public Account Flows Have No Rate Limiting

Login, registration, bootstrap, and invite acceptance have no application or edge rate limits,
lockout policy, or progressive delay.

Impact:

* Password brute force and credential stuffing.
* Public-registration account spam.
* Repeated invite-token or existing-user password attempts.

Recommendation:

* Add per-IP and per-account rate limits at the edge and application layer.
* Add security monitoring for repeated failed authentication attempts.
* Keep generic login and invite-token errors.

### 2. MCP Server Agent References Are Not Tenant-Validated

MCP server create/update schemas accept `agent_id`, and the repository stores it without validating
that the referenced agent belongs to the current organization.

Impact:

* An organization admin who knows another tenant's agent UUID can create a cross-tenant foreign-key
  relationship.
* Subsequent scoped reads limit direct data exposure, but the relationship violates tenant
  isolation and may become exploitable as MCP behavior expands.

Recommendation:

* Validate `agent_id` through the tenant-scoped agent repository on create and update.
* Add cross-organization MCP-agent reference tests.

### 3. Organization Admin User Mutations Still Affect Global Identity

User administration is scoped to current organization membership, but role updates also update
global `User.role`, and deactivation sets global `User.is_active=False`.

Impact:

* An admin in one organization can deactivate a user's access to every organization.
* Global-role changes can influence legacy fallback authorization and future multi-membership
  behavior.

Recommendation:

* Separate organization membership role/status management from global identity administration.
* Reserve global user deactivation for a platform-level administrator.
* Prevent last-organization-admin lockout.

### 4. Audit Snapshots Can Persist Sensitive Operational Data

Audit logs preserve complete before/after snapshots for executions, incidents, MCP servers, policy
decisions, users, and other governance objects. This can include:

* Execution input/output summaries and error messages.
* Incident descriptions and resolution notes.
* MCP server URLs and raw adapter error text.
* User email addresses and operational metadata.

Impact:

* Secrets or regulated data entered into free-text fields may become durable and visible to admins
  and auditors.
* MCP URLs may contain credentials or internal hostnames.

Recommendation:

* Add centralized audit redaction and field allowlists.
* Reject credentials embedded in MCP URLs.
* Define audit retention and sensitive-data handling policies.

### 5. Invite Tokens Are Returned and Transported in URLs

Invite tokens are strong (`secrets.token_urlsafe(32)`) and hashed at rest, but the raw token is
returned to the admin, displayed in the UI, copied to the clipboard, and placed in the
`/accept-invite?token=...` query string.

Impact:

* Tokens can leak through browser history, screenshots, clipboard managers, proxy logs, analytics,
  and referrer headers.

Recommendation:

* Apply a strict `Referrer-Policy`.
* Avoid third-party assets/scripts on invite pages.
* Consider exchanging the query token immediately for a short-lived server-side acceptance
  session, then remove it from the URL.

## Medium Priority Findings

### 1. JWT Hardening Is Minimal

Tokens expire after 60 minutes and inactive users are rejected, but tokens have no issuer,
audience, issued-at, not-before, JWT ID, refresh-token rotation, or per-token revocation.

Recommendation:

* Add `iss`, `aud`, `iat`, and `jti`.
* Validate issuer and audience.
* Introduce refresh-token rotation or short-lived access tokens with revocation support.

### 2. Frontend Stores Access Tokens in `localStorage`

Any successful XSS can read and exfiltrate the JWT. React escaping is used and no
`dangerouslySetInnerHTML`, `innerHTML`, `eval`, or equivalent sink was found, which reduces current
risk.

Recommendation:

* Add a strict Content Security Policy.
* Consider secure, HttpOnly, SameSite cookies for production authentication.

### 3. Auditor Can Mutate Incidents

The incident router grants Admin, Auditor, and Operator roles access to all create, update, resolve,
and dismiss operations. The frontend also exposes these actions to auditors.

Recommendation:

* Confirm this is intended.
* If auditors should be read-only, split incident read and mutation permissions.

### 4. MCP Error Details Are Returned and Stored Verbatim

MCP sync stores `str(exc)` in `last_error`, includes it in audit snapshots, and returns it in the
`502` API response.

Impact:

* A future real MCP adapter may expose internal network details, credentials, or stack-adjacent
  information.

Recommendation:

* Return stable public error messages and log sanitized diagnostic details separately.

### 5. MCP URLs Are Not Validated for Scheme or Network Safety

The current adapter is mock-only and performs no networking, so SSRF is not presently exploitable.
However, arbitrary strings are accepted as server URLs.

Recommendation:

* Before real MCP networking, enforce allowed schemes, block loopback/link-local/private networks
  as appropriate, prevent redirects to restricted networks, and add strict connect/read timeouts.

### 6. Request Size and Free-Text Field Limits Are Incomplete

Several descriptions, execution summaries, incident details, reasons, resolution notes, and error
fields have no maximum length. No application request-body limit was found.

Impact:

* Storage abuse, oversized audit snapshots, and memory/database denial-of-service pressure.

Recommendation:

* Add field maximums and an edge/application request-size limit.

### 7. Production API Documentation Is Public

FastAPI `/docs`, `/redoc`, and `/openapi.json` remain enabled in production. This does not bypass
authorization but improves endpoint discovery for attackers.

Recommendation:

* Disable or protect interactive docs in production, or restrict them at the edge.

### 8. CORS Safety Depends Entirely on Environment Configuration

CORS defaults to no origins, and deployment docs correctly recommend exact origins. The parser does
not reject wildcard or malformed production origins.

Recommendation:

* Reject `*`, non-HTTPS origins, and malformed values in production startup validation.

### 9. Database Security Relies on Application Scoping

No PostgreSQL row-level security was found. The deployment documentation uses a Supabase `postgres`
connection example, which is typically highly privileged.

Recommendation:

* Use a least-privileged application database role.
* Evaluate PostgreSQL RLS as defense in depth for organization-scoped tables.

### 10. Container Build and Runtime Run as Root

The backend Docker image installs dependencies and runs Uvicorn as root. It also installs `uv`
through a remote shell script without pinning a version or checksum.

Recommendation:

* Pin and verify build tooling.
* Run the final application as a non-root user.

## Low Priority Findings

### 1. Email Enumeration Is Possible

Public registration returns `409 Email already registered`. Bootstrap also distinguishes an
existing admin email before initialization.

Recommendation:

* Consider generic responses in public production flows.

### 2. Generated Vite Logs Are Tracked

`frontend/vite.stdout.log` and `frontend/vite.stderr.log` are committed. Current contents did not
trigger the likely-secret scan, but generated logs can accidentally capture environment details.

Recommendation:

* Remove generated logs from version control and ignore `*.log`.

### 3. Health Check Is Liveness Only

`/health` reveals no sensitive data, which is positive, but it does not verify database readiness.

Recommendation:

* Keep `/health` as liveness and add a bounded, non-diagnostic readiness endpoint.

### 4. Unscoped Login Audit Events Can Be Hidden

Login audit logs receive organization context only when the user has exactly one active
membership. Users with no membership or multiple memberships can create audit events with no
organization, making them invisible to organization audit-list endpoints.

Recommendation:

* Add a platform-security audit channel or explicit organization selection.

### 5. No Standard Security Response Headers Were Found

No application-level CSP, HSTS, `X-Content-Type-Options`, frame-ancestor policy, or referrer policy
was found. These may be supplied by Render or Vercel, but that was not verifiable from source.

Recommendation:

* Define and verify headers at the hosting edge.

## Positive Security Controls Already Present

* Argon2 password hashing through `pwdlib` recommended settings.
* Passwords and password hashes are excluded from public user schemas and audit snapshots.
* JWT expiry is enforced, algorithms are explicitly constrained, and inactive users are rejected.
* Authentication failures use generic invalid-credential messages.
* Invite tokens use approximately 256 bits of randomness and are stored only as SHA-256 hashes.
* Expired, revoked, accepted, and duplicate-membership invite paths are rejected.
* Organization invite management requires an actual admin membership, not global-role fallback.
* Backend authorization is the source of truth; frontend role guards only improve UX.
* Core organization-scoped repositories derive organization context from the authenticated session.
* Frontend resource requests do not submit `organization_id`.
* Cross-organization validation is present for agents, tools, policies, approvals, executions, and
  incidents.
* Audit logs, dashboard metrics, compliance reports, MCP servers, policies, executions, incidents,
  approvals, agents, tools, and users are scoped to the current organization.
* Critical governance mutations use atomic audit transactions.
* React escapes audit JSON and other rendered text; no direct HTML injection sink was found.
* CORS credentials are disabled and production documentation recommends exact HTTPS origins.
* Local `.env` files are ignored and not tracked.
* Likely-secret scan found no committed private keys, JWTs, or Supabase project URLs.
* `npm audit --omit=dev --audit-level=high` found zero vulnerabilities.
* `pip-audit` found no known vulnerabilities in the installed backend environment.

## Recommended Fix Order

1. Reject the default JWT secret in production and add production-config tests.
2. Secure fresh-deployment bootstrap and disable/gate legacy public registration in production.
3. Add authentication, registration, bootstrap, and invite-accept rate limiting.
4. Validate MCP `agent_id` references within the current organization.
5. Separate membership administration from global user role/deactivation.
6. Add audit snapshot redaction, MCP URL credential checks, and safe MCP error responses.
7. Harden invite-token transport and add security response headers.
8. Add request-size/field limits and confirm auditor incident mutation permissions.
9. Use a least-privileged database role and evaluate PostgreSQL RLS.
10. Harden JWT claims/revocation, production docs exposure, CORS validation, and container runtime.

## Proposed v0.4.1 Security Hardening Scope

Recommended bounded scope:

* Production startup validation:
  * Require a non-default `JWT_SECRET_KEY`.
  * Reject wildcard/non-HTTPS production CORS origins.
  * Add production configuration tests.
* Deployment bootstrap protection:
  * One-time bootstrap secret or trusted CLI bootstrap.
  * Disable legacy registration in production by default.
* Authentication abuse protection:
  * Rate limiting for login, register, bootstrap, and invite acceptance.
  * Failed-authentication security logging.
* Tenant/RBAC hardening:
  * MCP linked-agent tenant validation.
  * Organization membership role/status APIs separated from global user identity.
  * Confirm and enforce auditor incident permissions.
* Sensitive-data controls:
  * Central audit redaction.
  * MCP URL validation and credential rejection.
  * Sanitized MCP errors.
  * Request-size and free-text length limits.
* Browser/API hardening:
  * CSP, HSTS, frame restrictions, content-type, and referrer policies.
  * Protect or disable production OpenAPI/docs.
* Operational hardening:
  * Least-privileged PostgreSQL role.
  * Non-root Docker runtime.
  * Remove tracked generated logs.
* Security regression tests for all critical and high-priority findings.
