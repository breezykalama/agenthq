# AgentHQ v0.5.0 Real MCP Discovery Pre-Release Audit

## Summary

AgentHQ v0.5.0 Real MCP Discovery is **safe to release** for governed MCP tool discovery.

The audit confirmed that mock discovery remains the default, real discovery must be enabled
explicitly, the official MCP Python client is isolated behind the existing adapter boundary, and
sync continues to preserve tenant isolation and fail safely. Real discovery initializes an MCP
session and imports tool names and descriptions through `tools/list`; it does not execute tools.

Credentials are never accepted in MCP URLs or stored as raw values. Authenticated MCP servers
reference backend-only `MCP_AUTH_*` environment variables. The frontend and API expose only the
environment-variable reference name, never the referenced secret value.

## Audit Results

### Discovery Mode

* `MCP_DISCOVERY_MODE` accepts only `mock` or `real`.
* `mock` remains the default and uses the deterministic `MockMCPDiscoveryAdapter`.
* `real` selects `RealMCPDiscoveryAdapter`.
* Invalid values fail Pydantic settings validation.

### Real MCP Client Safety

* Streamable HTTP and SSE transports are supported.
* MCP sessions are initialized before paginated `tools/list` discovery.
* Connection and request timeouts are bounded and configurable per server.
* A total discovery timeout bounds initialization and tool pagination.
* HTTP redirects are disabled for both supported transports.
* Credentialed, malformed, and non-HTTP(S) URLs are rejected.
* Production blocks localhost and literal private, loopback, link-local, unspecified, and reserved
  IP addresses unless `ALLOW_PRIVATE_MCP_URLS=true`.
* Raw adapter and network exceptions are converted to stable sanitized client errors.
* Existing tools, linked agents, and previous successful `last_sync_at` values are preserved on
  discovery failure.

### Credential Handling

* Bearer tokens and API keys are loaded only from backend environment variables.
* Credential references must use the restricted `MCP_AUTH_*` namespace.
* Raw credentials are not accepted in request bodies, stored in database records, returned to the
  frontend, or written to audit snapshots.
* The frontend receives and displays only authentication type and credential reference name.
* Repository secret scanning found only documented placeholders and synthetic test credentials.

### Tenant Isolation

* MCP server create, list, get, update, delete, and sync operations require current organization
  context and MCP-management permission.
* MCP repository reads filter by current `organization_id`.
* Linked agents are resolved through organization-scoped agent queries.
* Cross-organization and soft-deleted linked agents are rejected.
* Discovered tools are created through the current organization-scoped linked agent.
* Cross-organization MCP server access returns a safe not-found response and is security-audited.

### Documentation

The README, deployment guide, environment example, and release notes document:

* `MCP_DISCOVERY_MODE=mock|real`.
* Streamable HTTP and SSE support.
* `MCP_AUTH_*` environment-referenced authentication.
* Per-server connection and request timeouts.
* Production private/local URL restrictions.
* Redirect behavior and credentialed URL rejection.
* Local real-MCP testing guidance.
* The intentional exclusion of real MCP tool execution.

### Repository Hygiene

* No `.env` files are tracked.
* No logs, local databases, caches, `node_modules`, or frontend build artifacts are tracked.
* `backend/.env` and generated frontend directories are ignored.
* No raw MCP credentials, JWTs, private keys, or production database credentials were found in
  changed source files.
* No files are staged and no commit was created.

## Issues Found

### Fixed: Unsafe Post-Discovery Processing Failure

If an MCP server returned unusable tool metadata, discovery could succeed but the tool-upsert phase
could return a generic server error without setting the MCP server to `error` or writing
`mcp_server.sync_failed`.

The sync service now routes post-discovery processing failures through the same sanitized failure
path while preserving atomic rollback behavior. Critical audit infrastructure failures remain
`503` responses and are not incorrectly reclassified as MCP discovery failures.

### Fixed: Local Full-Suite Test Isolation

Tenant-scoping tests could inherit a developer machine's Render-only `REDIS_URL`, causing unrelated
tests to fail closed when the internal Render hostname was unreachable locally. The tenant test
fixture now explicitly uses the in-memory test limiter without changing production behavior.

## Items Intentionally Deferred

* **DNS rebinding/private-address resolution:** production URL validation blocks localhost and
  literal private IP URLs, but does not resolve arbitrary public hostnames and verify every resolved
  address before connection. Redirects are disabled, which reduces SSRF risk, but DNS-rebinding
  protection should be considered before allowing untrusted organization administrators to register
  arbitrary MCP endpoints in high-assurance environments.
* **Live external MCP interoperability test:** automated tests use fakes around the official MCP
  client networking boundary. A controlled staging smoke test against a known real MCP server is
  recommended before enabling `MCP_DISCOVERY_MODE=real` in production.
* **Tool input schema persistence:** input schemas may be returned by MCP but are intentionally not
  stored in v0.5.0.
* **Tool execution:** real MCP tool execution is intentionally out of scope.

## Verification Results

* `uv run pytest`: **300 passed**
* `uv run ruff check .`: **passed**
* `uv run mypy app tests`: **passed**
* `npm run build`: **passed**
* `npm run lint`: **passed**
* `git diff --check`: **passed**
* Focused MCP, tenant, and transaction safety suite: **66 passed**
* New PostgreSQL migration SQL generation: **passed**
* Tracked artifact and likely-secret scans: **passed**

One existing Starlette deprecation warning is emitted by FastAPI's test client and is unrelated to
MCP discovery.

## Final Recommendation

**Safe to release**, with `MCP_DISCOVERY_MODE=mock` retained as the default.

Enable real mode first in a controlled staging environment, configure credentials only through
backend `MCP_AUTH_*` secrets, keep `ALLOW_PRIVATE_MCP_URLS=false` in production unless explicitly
required, and perform one live interoperability smoke test before production rollout.
