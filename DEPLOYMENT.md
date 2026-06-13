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
| `ALLOW_PUBLIC_REGISTRATION` | `false` | Public legacy/demo registration should remain disabled in production. |
| `REDIS_URL` | `redis://...` | Render Key Value internal URL used for production rate limiting. Protected endpoints fail closed when Redis is unavailable. |
| `RATE_LIMITS_ENABLED` | `true` | Enables centralized abuse protection. |
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

The repository includes [render.yaml](render.yaml) and a Dockerfile at `backend/Dockerfile`.

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
   * `ALLOW_PUBLIC_REGISTRATION`: `false`
   * `REDIS_URL`: Render Key Value internal Redis connection string
   * `RATE_LIMITS_ENABLED`: `true`
   * `MCP_DISCOVERY_MODE`: `real` to enable real MCP discovery
   * `ALLOW_PRIVATE_MCP_URLS`: `false` unless private MCP endpoints are explicitly approved
   * Any required `MCP_AUTH_*` credential variables
6. Deploy the `agenthq-api` web service.
7. Confirm `https://<service>.onrender.com/health` returns a successful response.

The container runs `alembic upgrade head` before starting Uvicorn and binds to Render's injected `PORT`.

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

### MCP Gateway Policy Enforcement

Create a server-scoped gateway token from the MCP Servers page or
`POST /api/v1/mcp-gateway-tokens`. The raw token is returned only on creation or rotation and must
be stored by the calling agent or MCP client as a secret.

Gateway clients send:

```text
Authorization: Bearer <gateway-token>
```

The REST-first v0.6.0 gateway exposes:

```text
GET  /api/v1/mcp-gateway/{mcp_server_id}/info
GET  /api/v1/mcp-gateway/{mcp_server_id}/tools
POST /api/v1/mcp-gateway/{mcp_server_id}/tools/{tool_id}/call
```

Full MCP Streamable HTTP protocol compatibility at the AgentHQ gateway endpoint is not included in
v0.6.0. Clients integrate through the REST gateway endpoints while the enforcement service remains
transport-independent for a future MCP-compatible facade.

The gateway hides unreviewed, disabled, and non-executable tools; evaluates policy before forwarding
calls; enforces approved approvals; records executions; and audits gateway outcomes. Gateway tokens
are hashed at rest, server-scoped, revocable, rotatable, and rate limited.

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
