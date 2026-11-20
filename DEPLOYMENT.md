# AgentHQ Deployment

This guide deploys AgentHQ with Supabase PostgreSQL, a Render backend, and a Vercel frontend.

## Required Environment Variables

Backend:

| Variable | Example | Notes |
| --- | --- | --- |
| `DATABASE_URL` | `postgresql://postgres.project-ref:password@aws-0-region.pooler.supabase.com:5432/postgres?sslmode=require` | Supabase PostgreSQL connection string. AgentHQ automatically selects the psycopg 3 SQLAlchemy driver. |
| `BACKEND_CORS_ORIGINS` | `https://agenthq.example.com,https://agenthq-git-main-team.vercel.app` | Comma-separated exact frontend origins. Do not use `*` in production. |
| `JWT_SECRET_KEY` | Strong random value of at least 32 characters | Signs access tokens. Never reuse another service secret. |
| `BOOTSTRAP_SECRET` | Separate strong random value | Protects first-organization bootstrap in production. |
| `FRONTEND_BASE_URL` | `https://agenthq.example.com` | Builds verification, reset, and invite links. Use the canonical HTTPS frontend origin. |
| `EMAIL_BACKEND` | `smtp` or `resend` | `resend` uses Resend's HTTPS API (required where SMTP egress is blocked, e.g. Railway Hobby). Use `console` only locally. Production console delivery is disabled to prevent token logging. |
| `EMAIL_FROM` | `AgentHQ <no-reply@example.com>` | Verified transactional sender identity. With `resend`, a sender on a domain verified in Resend. |
| `SMTP_HOST` | Provider SMTP hostname | Required when `EMAIL_BACKEND=smtp`. |
| `SMTP_PORT` | `587` | SMTP submission port. |
| `SMTP_USERNAME` | Provider credential | Store only in Render secrets. |
| `SMTP_PASSWORD` | Provider credential | Store only in Render secrets; never expose to the frontend. |
| `SMTP_USE_TLS` | `true` | Enables STARTTLS before authentication and delivery (ports 587/2587). |
| `SMTP_USE_SSL` | `false` | Implicit TLS for port 465. Mutually exclusive with `SMTP_USE_TLS`. |
| `SMTP_TIMEOUT_SECONDS` | `10` | Per-connection SMTP timeout used by the outbox worker. |
| `RESEND_API_KEY` | Resend API key | Required when `EMAIL_BACKEND=resend`. Backend secret only; never a `VITE_` variable. |
| `RESEND_TIMEOUT_SECONDS` | `10` | Per-request timeout for the Resend HTTPS API (max 60). |
| `EMAIL_OUTBOX_WORKER_ENABLED` | `true` | Runs the in-process email outbox worker. Keep enabled on the web service. |
| `EMAIL_OUTBOX_POLL_SECONDS` | `5` | Fallback poll interval; new mail is also dispatched immediately after commit. |
| `EMAIL_OUTBOX_MAX_ATTEMPTS` | `6` | Delivery attempts before a message is marked failed (backoff 30s to 1h). |
| `IDENTITY_MIN_RESPONSE_MS` | `400` | Constant response floor for forgot-password and resend-verification. |
| `ALLOW_PUBLIC_REGISTRATION` | `false` | Legacy/demo registration. Disabled unless explicitly `true`, in every environment. Registered accounts get no organization access. |
| `REDIS_URL` | `redis://...` | Render Key Value internal URL used for production rate limiting. Protected endpoints fail closed when Redis is unavailable. |
| `RATE_LIMITS_ENABLED` | `true` | Enables centralized abuse protection. |
| `TRUSTED_CLIENT_IP_HEADER` | unset (Render: `cf-connecting-ip`) | Single header holding the real client IP for IP-based rate limits. **Production enablement is BLOCKED until the ingress-spoofing test below passes.** Never `x-forwarded-for`. See [Client IP and rate limiting](#client-ip-and-rate-limiting). |
| `MCP_DISCOVERY_MODE` | `mock` or `real` | Selects deterministic demo discovery or real MCP protocol discovery. |
| `ALLOW_PRIVATE_MCP_URLS` | `false` | Keep false in production unless private MCP connectivity is explicitly approved. |
| `MCP_AUTH_*` | Secret value | Optional backend-only bearer token or API key referenced by an MCP server's `auth_secret_ref`. |
| `GATEWAY_LIST_RATE_LIMIT_ATTEMPTS` | `60` | Per-token/server governed tool-list requests per rate-limit window. |
| `GATEWAY_CALL_RATE_LIMIT_ATTEMPTS` | `30` | Per-token/tool governed calls per rate-limit window. |
| `GATEWAY_TOKEN_RATE_LIMIT_ATTEMPTS` | `10` | Gateway token management actions per rate-limit window. |

Frontend:

| Variable | Example | Notes |
| --- | --- | --- |
| `VITE_API_BASE_URL` | `https://agenthq-api.onrender.com` | Public Render API URL without a trailing slash. Vite embeds this value at build time. |

## Supabase Setup

1. Create a Supabase project and set a strong database password.
2. In the Supabase dashboard, select **Connect** and copy a connection string.
3. Prefer the Session pooler connection string for Render when the direct database endpoint is not reachable over IPv4.
4. Add `sslmode=require` to the connection string if it is not already present.
5. Store the full connection string as Render's `DATABASE_URL` secret. Never expose it to Vercel or client-side code.

AgentHQ uses SQLAlchemy and Alembic directly against PostgreSQL. It does not use the Supabase Data API.

## Render Backend Setup

The repository includes [render.yaml](render.yaml) and the production [Dockerfile](Dockerfile) at
the repository root (build context: repository root; it copies `backend/`). `backend/Dockerfile`
is used only by `docker-compose.yml` for local development.

1. Push the repository to GitHub, GitLab, or Bitbucket.
2. Create a Render Key Value service in the same region as the API. Use `noeviction` so security
   counters are not silently discarded.
3. Copy the Key Value service's internal Redis URL. Do not use `localhost` or expose the internal
   URL to the frontend.
4. In Render, create a Blueprint from the repository.
5. Set the secret environment variables:
   * `DATABASE_URL`: Supabase connection string
   * `BACKEND_CORS_ORIGINS`: exact Vercel production URL and any approved preview/custom domains
   * `JWT_SECRET_KEY`: strong random signing secret
   * `BOOTSTRAP_SECRET`: separate strong bootstrap secret
   * `FRONTEND_BASE_URL`: canonical Vercel production URL
   * `EMAIL_BACKEND`: `smtp` (or `resend`, see [Railway Staging](#railway-staging-resend-https-email))
   * `EMAIL_FROM`: verified sender address
   * `SMTP_HOST`, `SMTP_PORT`, `SMTP_USERNAME`, `SMTP_PASSWORD`, `SMTP_USE_TLS` (SMTP only)
   * `RESEND_API_KEY` (Resend only)
   * `ALLOW_PUBLIC_REGISTRATION`: `false`
   * `REDIS_URL`: Render Key Value internal Redis connection string
   * `RATE_LIMITS_ENABLED`: `true`
   * `MCP_DISCOVERY_MODE`: `real` to enable real MCP discovery
   * `ALLOW_PRIVATE_MCP_URLS`: `false` unless private MCP endpoints are explicitly approved
   * Any required `MCP_AUTH_*` credential variables
6. Deploy the `agenthq-api` web service.
7. Confirm `https://<service>.onrender.com/health` returns a successful response.

The container runs `alembic upgrade head` before starting Uvicorn and binds to Render's injected `PORT`.

### Transactional Email

AgentHQ supports two delivery backends:

* `smtp`: a provider-agnostic SMTP adapter. Resend, SendGrid, Postmark, Amazon SES, and similar
  providers can be used through their SMTP credentials.
* `resend`: Resend's HTTPS API (`POST https://api.resend.com/emails`), for platforms that block
  outbound SMTP. It sends `Authorization: Bearer <RESEND_API_KEY>`, a fixed `User-Agent`, and the
  outbox row's `Idempotency-Key`; it never follows redirects.

Verify the `EMAIL_FROM` domain or sender with the selected provider before deploying.

Organization bootstrap sends a 24-hour verification link. Password resets use 30-minute links and
always return a generic response to prevent account enumeration. Organization invitations include
the organization name, assigned role, and expiry. `FRONTEND_BASE_URL` must point to the public
frontend so links open the correct inline landing-page flow.

Only token hashes are stored. Raw tokens exist transiently while constructing email and are shown
only by the local console backend. SMTP passwords, Resend API keys, raw tokens, and passwords are
excluded from audit metadata and application security logs. Provider error messages are never
logged or stored; only a fixed reason code, the HTTP status, and Resend's error `name` are.

#### Delivery model (transactional outbox)

Identity emails are never sent inside an HTTP request. Bootstrap, invite creation, forgot-password,
and resend-verification write the token hash and an `email_outbox` row in the same database
transaction. An in-process worker thread delivers the message only after that transaction commits,
so a link is never emailed for a token that was rolled back, and SMTP latency never reaches the
public request path.

* No raw token is stored, not even encrypted. Each outbox row holds a random nonce; the raw token is
  `HMAC(key derived from JWT_SECRET_KEY, nonce)` and is re-derived at send time. The nonce is cleared
  when the row is sent, cancelled, or permanently failed.
* Rotating `JWT_SECRET_KEY` invalidates undelivered links. The worker detects the mismatch and marks
  those rows failed instead of sending a dead link; users request a new link.
* Superseded, used, revoked, or expired tokens are cancelled at send time rather than emailed.
* Failures retry with backoff up to `EMAIL_OUTBOX_MAX_ATTEMPTS`. Every attempt is audited
  (`auth.email_verification_failed`, `auth.password_reset_email_failed`,
  `organization_invite.email_failed`) with a sanitized error code and no provider text.
* A failure the provider reports as permanent ends the row as failed immediately instead of
  retrying. With Resend that is a rejected request (400/422), a wrong endpoint (404/405), or an
  idempotency key reused with a different body. Timeouts, network errors, 401/403 (key or sender
  misconfiguration that an operator can fix), 408, 409 in-progress, 429 (rate limit or quota),
  5xx, and malformed success responses are retried. A malformed 2xx is never counted as sent.
* Delivery is at-least-once. A crash after the provider hand-off but before the status update
  causes a retry after the 2-minute lease expires. Every attempt for a row uses the same
  idempotency key (`agenthq-email-outbox-<row id>`), and Resend keeps keys for 24 hours and returns
  the original result, so with `resend` such a retry does not send a second email. Duplicates
  remain possible with SMTP, or with Resend only if a retry happens more than 24 hours after the
  first attempt. The retry schedule alone never gets there (about 1.7 hours by default, under 16
  hours at the maximum of 20 attempts); the service being down for more than a day while a row is
  pending would.
* A row's request body must stay identical across attempts for its key. If it changes (for example
  an organization is renamed between attempts of an invite email), Resend answers 409
  `invalid_idempotent_request` and the row is marked failed without a second send.
* Rows left pending while the Render instance sleeps or restarts are delivered on the next start.
  Multiple instances are safe: rows are claimed with `SELECT ... FOR UPDATE SKIP LOCKED`.

Invite creation now returns `email_delivery: "queued" | "disabled"` instead of `email_sent`, because
delivery happens after the response. In production, bootstrap and invite creation return 503
before writing anything if no delivery channel is configured.

#### Email verification enforcement

* Mandatory: administrators created by organization bootstrap on v0.8.1 or later
  (`users.email_verification_required = true`). Until verified they can sign in, call
  `/api/v1/auth/me`, verify, resend verification, and reset their password. Every
  organization-scoped API returns `403 Email verification required.`
* Grandfathered: every account that existed before migration `202611170001`, including existing
  unverified administrators. The column defaults to false, so nobody is locked out by the deploy.
  These users may still verify voluntarily through resend-verification.
* Not required: users who join through an invitation (holding the emailed invite token verifies the
  address) and legacy/demo self-registered users.

#### Session invalidation

Access tokens carry an `av` (auth version) claim. A completed password reset increments
`users.auth_version` atomically, so every access token issued earlier is rejected immediately.
Tokens issued before this release carry no claim and are treated as version 0, so the deploy does
not sign anyone out.

#### Abuse limits

Forgot-password and resend-verification are limited per IP and per email by the shared rate limiter,
and additionally per account: at most one message per 60 seconds and five per hour. Throttled
requests return the same generic response, are padded to `IDENTITY_MIN_RESPONSE_MS`, and are
audited with outcome `denied`.

#### Token URLs

Emailed links carry the token in the URL fragment (`/?auth=verify-email#token=...`), which browsers
do not send to Vercel, in Referer headers, or to third parties. The frontend removes the token from
the address bar on load and keeps it in tab-scoped `sessionStorage` so a refresh still works. The
frontend (`vercel.json`, `index.html`) and the API set `Referrer-Policy: no-referrer`. Legacy
`?token=` links and the `/accept-invite`, `/verify-email`, and `/reset-password` routes still work.

### Railway Staging (Resend HTTPS Email)

Railway disables outbound SMTP on its Free, Trial, and Hobby plans and recommends HTTPS email APIs
instead. Use the native Resend backend there; it needs no SMTP settings.

Set these on the Railway API service only:

```
EMAIL_BACKEND=resend
RESEND_API_KEY=<secret: Resend API key with sending access only>
EMAIL_FROM=<sender on a domain verified in Resend, e.g. "AgentHQ Staging <no-reply@staging.example.com>">
FRONTEND_BASE_URL=<staging frontend HTTPS URL>
```

* Store `RESEND_API_KEY` as a secret service variable. It belongs to the backend only: never put it
  in any `VITE_` variable, the Vercel project, the repository, or a shared Railway variable that a
  frontend service can read. Anything prefixed `VITE_` is compiled into public JavaScript.
* Create a separate, sending-only key for each environment and revoke it when the environment is
  torn down.
* Leave the `SMTP_*` variables unset. `RESEND_TIMEOUT_SECONDS` (default `10`) bounds each request.
* Startup validation (which runs before migrations) rejects a missing or malformed key, an invalid
  `EMAIL_FROM`, a `.local` sender in production, and a non-public or non-HTTPS
  `FRONTEND_BASE_URL` in production. Validation errors never echo configuration values.
* Railway builds the root `Dockerfile` from the repository root. Leave the service's Root
  Directory empty.

### Client IP and rate limiting

Unauthenticated endpoints (login, register, bootstrap, forgot/reset password, verify and resend
verification, invite acceptance) are limited per client IP in addition to per email or token.
On Render the TCP peer is the platform proxy, so **with no configuration every user shares one
IP bucket**. A single client making `AUTH_RATE_LIMIT_ATTEMPTS` failed attempts then blocks
everyone else for the window. Per-email, per-token, per-organization, per-user and gateway
limits are not affected.

**`TRUSTED_CLIENT_IP_HEADER`** (unset by default) names one header that the edge proxy sets to
the real client address:

* When unset, the socket peer is used.
* When set, the header is used only if all of these hold:
  * the socket peer is an internal address (private, loopback, link-local or shared/CGNAT);
  * exactly one such header is present;
  * its value is a single valid IPv4 or IPv6 address.
* Anything else falls back to the socket peer.
* Forwarding chains (`x-forwarded-for`, `forwarded`) are refused at startup and never read.
* Production logs `security_client_ip_header_unset` at startup when it is not set.
* IPv6 clients are bucketed per `/64`. Logs keep the full address.

**Trust assumption (not verifiable by the application).** A valid IP in the header proves
nothing about who wrote it. On Render, `CF-Connecting-IP` is trustworthy only because:

1. Cloudflare overwrites any client-supplied `CF-Connecting-IP` on every request reaching a
   public Render web service. This is stated in Render's articles and must be confirmed
   below.
2. The public internet reaches the service only through that ingress.
3. Nothing else that can reach the service directly sends a forged value. Requests over
   Render's private network (other services in the same workspace and region) bypass
   Cloudflare and could set this header to anything. The application cannot tell them apart
   from the platform proxy, because both arrive from internal addresses. Do not enable the
   setting if any untrusted workload can reach the service privately.

**Never set `FORWARDED_ALLOW_IPS=*` (or `--forwarded-allow-ips="*"`).** Uvicorn then takes the
*leftmost* `X-Forwarded-For` entry, which the caller controls, so any client can choose its
rate-limit identity. Trusting private ranges such as `10.0.0.0/8` does not help either, because
the rightmost untrusted hop is a shared Cloudflare edge. Leave Uvicorn's default trust
(`127.0.0.1`) unchanged; `TRUSTED_CLIENT_IP_HEADER` replaces forwarded-header parsing.

**Required ingress-spoofing test (staging, before enabling in production):**

1. Deploy with `TRUSTED_CLIENT_IP_HEADER=cf-connecting-ip`.
2. From a machine whose public IP you know, send failed logins to the public URL with a forged
   header, for example `-H "CF-Connecting-IP: 192.0.2.123"`, until one returns `429`.
3. In the service logs, the `security_rate_limit_exceeded ... client_ip=` line must show
   **your real public IP**, not `192.0.2.123`.
4. Repeat from a second network (for example a phone hotspot). It must get its own bucket:
   `401` responses while the first network is still limited.
5. Check that the platform has no other service able to reach this one over the private
   network.

These log lines contain the scope and client IP only, never credentials or email addresses.
Use throwaway addresses such as `nobody@example.com` and wrong passwords, never real
accounts.

If any step fails, unset the variable. The service then falls back to the socket peer, which
gives shared buckets but cannot be spoofed.

### Real MCP Discovery

Real discovery supports Streamable HTTP and SSE transports. AgentHQ initializes an MCP session and
uses `tools/list`. Real tool calls occur only when a client explicitly uses the AgentHQ MCP Gateway.

Configure authentication without putting credentials in URLs:

1. Add a backend-only Render secret such as `MCP_AUTH_CUSTOMER_OPERATIONS`.
2. Register the MCP server with `auth_type` set to `bearer` or `api_key`.
3. Set `auth_secret_ref` to the environment variable name, not its value.

AgentHQ sends bearer credentials in `Authorization: Bearer ...` and API keys in `X-API-Key`.
Credential references must begin with `MCP_AUTH_`. HTTP redirects are disabled for discovery.
Production rejects localhost and literal private, loopback, or link-local IP URLs unless
`ALLOW_PRIVATE_MCP_URLS=true`.

Each MCP server supports bounded `connect_timeout_seconds` and `request_timeout_seconds`. Discovery
failures preserve existing linked agents, discovered tools, and the previous successful
`last_sync_at`; clients receive a stable sanitized error.

### Dual-Protocol MCP Gateway Policy Enforcement

Create an agent-scoped gateway credential from the MCP Servers page or
`POST /api/v1/agent-gateway-credentials`. The raw credential is returned only on creation or
rotation and must be stored by the calling agent or MCP client as a secret.

Gateway clients send:

```text
Authorization: Bearer <gateway-token>
```

The REST gateway exposes:

```text
GET  /api/v1/gateway/mcp-servers
GET  /api/v1/gateway/mcp-servers/{mcp_server_id}/tools
POST /api/v1/gateway/mcp-servers/{mcp_server_id}/tools/{tool_id}/call
```

MCP-compatible clients connect through Streamable HTTP at
`https://<agenthq-host>/api/v1/mcp/<mcp_server_id>` using the agent gateway credential as a Bearer
token. The endpoint supports `initialize`, `notifications/initialized`, `tools/list`, and
`tools/call`. See [GATEWAY_INTEGRATION.md](GATEWAY_INTEGRATION.md) for approval and idempotency
metadata.

The gateway hides unreviewed, disabled, and non-executable tools; evaluates policy before forwarding
calls; enforces approved approvals; records executions; and audits gateway outcomes. Gateway tokens
are hashed at rest, server-scoped, revocable, rotatable, and rate limited.

Gateway tool-call input payloads are limited to 64 KiB. Oversized REST requests are rejected with
validation errors, and oversized MCP `tools/call` arguments return a safe JSON-RPC parameter error.

When an `idempotency_key` is supplied, repeated calls using the same gateway token and tool return
the previous execution status and safe summary without calling the upstream tool again. Full prior
tool output is intentionally not persisted for replay.

Approval reuse is allowed in v0.6.0 when the approval is approved, belongs to the same organization
and agent, and its `requested_action` exactly matches the tool name. The reused approval ID is
included in gateway audit metadata.

Strict enforcement requires network and credential controls that prevent governed clients from
calling upstream MCP servers directly. If a client retains a direct upstream URL and credential, it
can bypass AgentHQ.

### Migration Command

Run migrations from a Render shell or a trusted local environment:

```bash
cd backend
uv run alembic upgrade head
```

For multi-instance production deployments, run migrations as a controlled pre-deploy step instead of concurrently on every instance.

### Seed Command

Seed data is optional and should normally be used only for demo environments:

```bash
cd backend
uv run python -m app.seed
```

Do not automatically seed a production database.

## Vercel Frontend Setup

1. Import the repository into Vercel.
2. Set the project root directory to `frontend`.
3. Use the detected Vite settings:
   * Build command: `npm run build`
   * Output directory: `dist`
4. Set `VITE_API_BASE_URL` to the public Render API URL.
5. Deploy, then add the Vercel production origin to Render's `BACKEND_CORS_ORIGINS`.

`frontend/vercel.json` provides the SPA rewrite needed for React Router deep links.

## Production Safety

* Keep `DATABASE_URL` only in Render's secret environment variables.
* Keep `JWT_SECRET_KEY`, `BOOTSTRAP_SECRET`, and `REDIS_URL` only in secret environment variables.
* Keep `SMTP_PASSWORD`, `RESEND_API_KEY`, and provider credentials only in backend secret
  environment variables (Render or Railway). Never expose them through `VITE_` variables.
* Keep all `MCP_AUTH_*` values only in backend secret environment variables.
* Store raw gateway tokens only in the calling client's secret store; AgentHQ shows them once.
* Restrict direct upstream MCP access when using AgentHQ as an enforcement boundary.
* Configure exact HTTPS CORS origins; do not use wildcard origins.
* Keep rate limiting enabled in production. See [RATE_LIMITING.md](RATE_LIMITING.md).
* Apply migrations before serving a new application version.
* Do not seed production automatically.
* The FastAPI `/docs` and `/redoc` routes remain enabled for this MVP. Restrict them at the edge if the API should not expose interactive documentation publicly.
* Review Supabase network restrictions and database access controls before handling sensitive data.

## Common Deployment Issues

### Render cannot connect to Supabase

Use Supabase's Session pooler connection string when the direct endpoint is unavailable from an IPv4-only network. Confirm the password is URL-encoded and SSL is enabled.

### Render reports no open port

Confirm the service uses the included Dockerfile. It binds Uvicorn to `0.0.0.0` and Render's `PORT`.

### Alembic fails during startup

Check `DATABASE_URL`, database reachability, and whether another instance is running the same migration concurrently. Run `uv run alembic current` from a Render shell to inspect the database revision.

### Browser requests fail with CORS errors

Add the exact Vercel origin to `BACKEND_CORS_ORIGINS`, without a path or trailing slash, then redeploy the backend.

### Frontend calls the wrong API

Vite embeds `VITE_API_BASE_URL` during the build. Update the variable in Vercel and trigger a new frontend deployment.

### Frontend deep links return 404

Confirm `frontend/vercel.json` is included in the Vercel deployment and the Vercel project root is `frontend`.

### Protected API requests return 503

AgentHQ fails closed when production abuse protection is unavailable. Confirm `REDIS_URL` is the
Render Key Value internal URL, both services are in the same region, and the Key Value service is
healthy. A Render internal hostname is not reachable from a local development machine.
