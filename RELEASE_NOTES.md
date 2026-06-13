# AgentHQ v0.2.0 — MCP Server Registration & Tool Discovery

AgentHQ v0.2.0 expands the governance platform with MCP server registration and adapter-based tool discovery.

## Highlights

* Added MCP Server Registration
* Added MCP Tool Discovery via adapter-based discovery
* Added linked agent creation during sync
* Added idempotent tool sync
* Added MCP sync audit logs
* Added MCP server dashboard counts
* Increased automated test coverage to 170 passing tests

## MCP Registration

Registered MCP servers track connection status, linked agents, synchronization timestamps, and the latest discovery error. Soft-deleted servers remain excluded from active registry results and dashboard counts.

## Tool Discovery

The v0.2.0 discovery flow uses a mock/local adapter behind an interface designed for future real MCP clients. Successful synchronization creates or reuses a linked agent and upserts discovered tools into the Agent Tools Registry.

Repeated synchronization does not duplicate tools. Discovery can update tool descriptions while preserving manually governed permission and risk-level settings.

## Auditability

AgentHQ records `mcp_server.synced` and `mcp_server.sync_failed` audit events with structured before/after snapshots.

## Verification

* 170 automated backend tests passing
* Ruff clean
* MyPy clean
* MCP migrations verified against PostgreSQL

# AgentHQ v0.3.0 — Authentication & RBAC

AgentHQ v0.3.0 introduces enterprise identity, authentication, and role-based access control across the governance platform.

## Highlights

* JWT Authentication
* User Management
* Role-Based Access Control
* Agent Ownership Enforcement
* Protected Governance Endpoints
* Dashboard User Metrics
* 183 Automated Tests Passing

## Authentication

Users can register, sign in, persist an access token, load their current identity, and sign out through the AgentHQ frontend. Passwords are hashed with Argon2 and are never stored as plaintext.

## Role-Based Access Control

AgentHQ supports Admin, Auditor, Operator, and Agent Owner roles. Governance endpoints enforce role permissions, while agent owners can access and manage only agents assigned to their email identity.

## Protected Governance

RBAC protects policy rules, MCP servers, audit logs, compliance reports, executions, incidents, agent management, and administrative user management.

## Dashboard

The dashboard summary now reports total users and active users.

## Verification

* 183 automated backend tests passing
* Ruff clean
* MyPy clean
* Frontend build and lint passing
* Live frontend and backend deployment

# AgentHQ v0.3.2 — Reliability & Performance Hardening

## Highlights

### Reliability

* Added service-owned atomic transactions
* Added rollback tests for critical governance flows
* Eliminated partial-state risks for key operations

### Performance

* Added pagination across all major list endpoints
* Added 16 PostgreSQL indexes
* Optimized dashboard aggregates
* Optimized compliance reporting
* Added query-count regression tests

### Quality

* 201 automated tests passing
* Ruff clean
* MyPy clean

## Metrics

Dashboard Summary:
24 → 6 queries

Compliance Summary:
10 → 5 queries

Agent Compliance Report:
10 → 2 queries

# AgentHQ v0.4.0 - Multi-Tenant Foundations

## Highlights

### Organizations

* Organization workspaces
* Memberships
* Bootstrap organization creation

### User Management

* Organization invitations
* Invite acceptance
* Membership roles

### Tenant Isolation

* Organization-scoped governance resources
* Cross-organization access protection
* Tenant-aware dashboards and compliance reports

### User Experience

* Organization-aware onboarding
* Organization-aware navigation
* Audit Logs UI
* Invite management UI

### Reliability

* Atomic transactions
* Failure handling
* Query optimization
* Pagination
* PostgreSQL indexes

### Quality

* 220 automated tests passing
* Ruff clean
* MyPy clean

# AgentHQ v0.4.1 - Security Hardening & Abuse Protection

## Highlights

### Authorization and Tenant Isolation

* Centralized organization membership, role, permission, and resource-scope checks
* Hardened cross-organization reference validation
* Membership-level user administration
* Last-active-admin lockout prevention
* Read-only auditor incident permissions

### Audit and Sensitive Data Protection

* Append-only, organization-scoped audit logs
* Security events for denied and cross-tenant access attempts
* Request ID, actor, organization, IP address, and user-agent context
* Recursive audit redaction for secrets and credentials
* Safe MCP URL validation and sanitized MCP errors

### Authentication and Abuse Protection

* Production JWT-secret validation
* Bootstrap-secret protection
* Production public-registration gating
* Redis-backed production rate limiting
* In-memory local/test limiter
* Actor-, organization-, resource-, IP-, and identifier-aware rate-limit keys
* `429` responses with `Retry-After`
* Rate-limit denial security events

### Database Defense in Depth

* Supabase public-schema Row Level Security lockdown
* Server-only access model retained through FastAPI

### Quality

* 282 automated backend tests passing
* Ruff clean
* MyPy clean
* `git diff --check` clean

# AgentHQ v0.5.0 - Real MCP Tool Discovery

## Highlights

* Added real MCP protocol discovery through the official Python MCP client.
* Added Streamable HTTP and SSE transport support.
* Added MCP session initialization and paginated `tools/list` discovery.
* Added selectable `mock` and `real` discovery modes.
* Added environment-referenced bearer and API-key authentication.
* Added bounded connection and request timeouts.
* Disabled discovery redirects to preserve MCP URL safety controls.
* Preserved linked agents, tools, and successful sync timestamps on discovery failure.
* Kept client-facing and stored sync errors sanitized.

Real MCP tool execution remains out of scope for this release.
# AgentHQ v0.5.1 - Tool Schema Governance

## Highlights

* Persisted MCP tool input and output schemas using PostgreSQL JSONB.
* Added deterministic schema hashes, schema versions, and change timestamps.
* Added audit events for discovered, removed, schema-changed, and description-changed tools.
* Added explicit administrator and operator tool review workflow.
* Added computed unreviewed, reviewed, and governed statuses.
* Added policy coverage details, governance reporting, dashboard metrics, and schema viewer UI.
* Preserved organization isolation, audit redaction, and manually edited risk and permission values.
* MCP tool execution remains intentionally out of scope.

## Quality

* 305 automated backend tests passing
* Ruff clean
* MyPy clean
* Frontend build and lint passing
# AgentHQ v0.5.2 - Governance Alerts & Monitoring

## Highlights

* Added organization-scoped governance alerts with audited lifecycle management.
* Added automatic alerts for MCP tool discovery, removal, schema drift, and description changes.
* Added alerts for high-risk unreviewed tools, ungoverned tools, and lost policy coverage.
* Added idempotent active-alert generation and redacted alert metadata.
* Added governance health scoring and dashboard monitoring metrics.
* Added responsive Governance Alert Center and tool-level alert links.
* Preserved tenant isolation, optimized dashboard query counts, and safe cross-tenant not-found behavior.
* Notifications, email delivery, and MCP tool execution remain intentionally out of scope.

## Quality

* 311 automated backend tests passing
* Ruff clean
* MyPy clean
* Frontend build and lint passing

# AgentHQ v0.5.3 - Policy Simulation & Impact Analysis

## Highlights

* Added organization-scoped, read-only policy simulation.
* Added affected tool, agent, and MCP server impact analysis.
* Added current and projected policy coverage comparison.
* Added governance-effect projections for block, require-approval, and allow outcomes.
* Added overlapping-policy and conflicting-effect warnings.
* Added estimated governance-gap and alert resolution impact.
* Added preview-before-save support for policy creation and updates.
* Added policy coverage percentage to the dashboard.
* Preserved policy enforcement and execution behavior without simulation side effects.

## Quality

* 320 automated backend tests passing
* Ruff clean
* MyPy clean
* Frontend build and lint passing
