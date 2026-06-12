# AgentHQ

AgentHQ is a multi-tenant AI Agent Governance Platform that helps organizations safely operate, monitor, and govern AI agents through policies, approvals, audit trails, compliance reporting, incident management, and MCP integrations.

Organizations can create dedicated governance workspaces, invite users, assign roles, onboard MCP servers, and maintain visibility into AI agent activity across their environment.

## Live Demo

Frontend:
[https://agenthq-seven.vercel.app/](https://agenthq-seven.vercel.app/)

Backend API:
[https://agenthq.onrender.com/docs](https://agenthq.onrender.com/docs)

## Current Version

AgentHQ v0.5.0

## Project Status

AgentHQ is a live, multi-tenant Enterprise AI Agent Governance Platform focused on:

* Organization Workspaces
* Membership-Based Access
* Tenant Isolation
* Agent Governance
* Policy Enforcement
* Approval Workflows
* Execution Tracking
* Incident Management
* Audit Logging
* Compliance Reporting
* MCP Server Registration
* MCP Tool Discovery
* Authentication & RBAC
* Security Event Trails
* Centralized Abuse Protection
* Real MCP Tool Discovery

## The Problem

Organizations are rapidly deploying AI agents across operations, customer service, knowledge management, and business workflows.

As the number of agents grows, organizations need answers to critical governance questions:

* Which agents exist?
* What tools can they access?
* Which actions require approval?
* Which executions were blocked?
* What incidents occurred?
* How do we audit agent activity?
* How do we generate compliance reports?

## The Solution

AgentHQ provides:

* Agent Registry
* Agent Tools Registry
* Policy Rules
* Policy Decision Engine
* Approval Workflows
* Execution Tracking
* Incident Management
* Audit Logging
* Compliance Reporting
* Dashboard Analytics

## AgentHQ v0.5.0

AgentHQ v0.5.0 adds real MCP protocol tool discovery while preserving the deterministic mock
adapter for demos and tests.

* Connect to MCP servers over Streamable HTTP or SSE.
* Initialize an MCP client session and discover tools through `tools/list`.
* Select mock or real discovery with `MCP_DISCOVERY_MODE`.
* Configure bounded connection and request timeouts per MCP server.
* Reference bearer tokens or API keys through `MCP_AUTH_*` environment variables.
* Disable HTTP redirects and preserve existing linked agents, tools, and successful sync timestamps
  when discovery fails.
* Keep sync failures sanitized and auditable.

Real discovery imports tool names and descriptions only. AgentHQ does not execute MCP tools.

## AgentHQ v0.2.0

AgentHQ v0.2.0 introduces MCP Server Registration and Tool Discovery.

This allows AgentHQ to:

* Register MCP servers
* Track MCP server connection status
* Automatically create linked agents
* Discover tools from MCP servers
* Sync discovered tools into the Agent Tools Registry
* Preserve manually edited tool risk levels and permissions
* Prevent duplicate tools during repeated syncs
* Audit successful and failed MCP sync operations
* Show MCP server counts on the dashboard

See [RELEASE_NOTES.md](RELEASE_NOTES.md) for the complete v0.2.0 release summary.

## AgentHQ v0.3.0

### Authentication & RBAC

Added:

* User management
* JWT authentication
* Login and registration
* Role-based access control

Roles:

* Admin
* Auditor
* Operator
* Agent Owner

### Enterprise Access Control

Protected:

* Policy Rules
* MCP Servers
* Audit Logs
* Compliance Reports
* Executions
* Incidents
* Agent Management

### Dashboard

Added:

* Total users
* Active users

## AgentHQ v0.3.2

AgentHQ v0.3.2 focuses on reliability, performance, and production hardening.

### Pagination

Added bounded pagination to:

* Agents
* Agent Tools
* MCP Servers
* Policy Rules
* Approvals
* Executions
* Incidents
* Audit Logs
* Users
* Compliance Incidents

Default:

* `limit = 50`
* `max limit = 200`

### Database Performance

Added production indexes for:

* Audit Logs
* Executions
* Incidents
* Approvals
* Agent Tools
* Policy Rules
* MCP Servers

### Query Optimization

Reduced query fan-out:

Dashboard Summary:

* 24 → 6 queries

Compliance Summary:

* 10 → 5 queries

Agent Compliance Report:

* 10 → 2 queries

### Transaction Safety

Added service-owned atomic transactions for:

* Execution Creation
* Approval Decisions
* MCP Sync
* User Deactivation
* Policy Decision Evaluation

Critical governance actions now commit business mutations and audit logs atomically.

## AgentHQ v0.4.0

AgentHQ v0.4.0 introduces multi-tenant organization foundations for independently governed enterprise workspaces.

Highlights:

* Organization workspaces and membership-based roles
* Organization bootstrap and administrator creation
* Organization invitations and invite acceptance
* Tenant-isolated governance resources
* Organization-aware dashboards, compliance reports, navigation, and onboarding
* Audit Logs frontend for organization admins and auditors

See [RELEASE_NOTES.md](RELEASE_NOTES.md) for the complete v0.4.0 release summary.

## AgentHQ v0.4.1

AgentHQ v0.4.1 focuses on security hardening for multi-tenant, production-facing deployments.

Highlights:

* Centralized organization authorization and tenant-isolation checks
* Membership-level administration and last-admin lockout prevention
* Append-only, organization-scoped audit logs and denied-access security events
* Recursive audit redaction and safe MCP error handling
* Production JWT, bootstrap, registration, and MCP URL safeguards
* Redis-backed production rate limiting with local in-memory fallback
* `429 Too Many Requests` responses with `Retry-After`
* Rate-limit security audit events for protected operations

See [SECURITY_AUDIT.md](SECURITY_AUDIT.md), [AUTHORIZATION.md](AUTHORIZATION.md),
[AUDIT_LOGGING.md](AUDIT_LOGGING.md), and [RATE_LIMITING.md](RATE_LIMITING.md) for the security
model and operational guidance.

## Architecture Overview

```text
Organization
|-- Memberships
|-- Agents
|-- MCP Servers
|-- Policy Rules
|-- Executions
|-- Incidents
|-- Audit Logs
`-- Compliance Reports
```

Organizations own governance resources, while memberships define each user's organization role. Tenant isolation prevents cross-organization access, audit logs provide governance visibility, policies govern execution behavior, and MCP integrations connect external agent ecosystems to the AgentHQ governance layer.

## Architecture

![AgentHQ Architecture](docs/images/agenthq-architecture.png)

AgentHQ uses a React frontend for the tenant-aware governance console, a FastAPI backend for API workflows, modular governance services for policy decisions and lifecycle rules, PostgreSQL persistence for organization-scoped operational records, and audit/compliance capabilities for reporting and review.

The architecture includes organization and membership context, tenant-isolation enforcement, JWT authentication, reusable RBAC enforcement, an MCP Server Registry, and an MCP Discovery Layer that synchronizes discovered tools into the governance layer.

## Core Capabilities

### Multi-Tenant Organizations

* Organization workspaces
* Membership-based access
* Tenant isolation

### Governance

* Policy Rules
* Policy Decision Engine
* Approval Workflows
* Execution Tracking

### Operations

* Incident Management
* Compliance Reporting
* Dashboard Monitoring

### MCP Integration

* MCP Server Registration
* Tool Discovery
* Tool Governance

### Security & Reliability

* RBAC
* Audit Logging
* Atomic Transactions
* Failure Handling
* Pagination
* Performance Optimization
* Tenant Isolation
* Audit Redaction
* Security Event Trails
* Redis-Backed Rate Limiting

## Tech Stack

### Backend

* FastAPI
* PostgreSQL
* SQLAlchemy
* Alembic

### Frontend

* React
* TypeScript
* Tailwind CSS
* TanStack Query

### Infrastructure

* Docker Compose
* Supabase PostgreSQL
* Render
* Vercel
* Render Key Value / Redis

## Quality

* 282 automated tests passing
* Ruff clean
* MyPy clean
* PostgreSQL migrations verified
* Dockerized deployment
* Render backend
* Vercel frontend
* Supabase PostgreSQL
* Query-count regression tests
* Atomic transaction safety
* Tenant isolation tests
* Append-only audit logging
* Centralized secret redaction
* Redis-backed production abuse protection

## Organization Onboarding

```text
Create Organization
        |
Create Organization Admin
        |
Invite Users
        |
Accept Invite
        |
Assign Roles
        |
Govern AI Agents
```

Each organization operates as an independently governed workspace. Membership roles control access, and tenant isolation ensures that users and governance resources remain separated across organizations.

## Repository Structure

```text
backend/
  app/
    api/
    core/
    db/
    models/
    repositories/
    schemas/
    services/
  alembic/
  tests/
  Dockerfile
  pyproject.toml

frontend/
  src/
    api/
    components/
    pages/
    routes/
    types/
  package.json
```

## Docker Demo

Start PostgreSQL and the backend API:

```bash
docker compose up --build
```

The API container runs migrations before starting Uvicorn.

Open API docs:

```text
http://localhost:8000/docs
```

Seed demo data manually:

```bash
docker compose exec api python -m app.seed
```

Stop the stack:

```bash
docker compose down
```

Reset local database data:

```bash
docker compose down -v
```

## Production Deployment

AgentHQ is prepared for a Supabase PostgreSQL, Render backend, and Vercel frontend deployment.

Production configuration is environment-driven:

```text
Backend:  DATABASE_URL, BACKEND_CORS_ORIGINS, JWT_SECRET_KEY, BOOTSTRAP_SECRET, REDIS_URL,
          ALLOW_PUBLIC_REGISTRATION, RATE_LIMITS_ENABLED, MCP_DISCOVERY_MODE
Frontend: VITE_API_BASE_URL
```

Use exact HTTPS origins in `BACKEND_CORS_ORIGINS`, keep backend credentials in secret storage,
configure Render's internal Redis URL as `REDIS_URL`, apply migrations before serving a new
version, and never seed production automatically. Protected operations fail closed when production
rate limiting is unavailable. FastAPI interactive docs remain enabled for the current release and
can be restricted at the edge when needed.

See [DEPLOYMENT.md](DEPLOYMENT.md) and [RATE_LIMITING.md](RATE_LIMITING.md) for the complete
deployment and abuse-protection guidance.

## Documentation

* [Deployment Guide](DEPLOYMENT.md)
* [Demo Flow](DEMO.md)
* [Release Notes](RELEASE_NOTES.md)
* [Organization Authorization](AUTHORIZATION.md)
* [Audit Logging](AUDIT_LOGGING.md)
* [Rate Limiting](RATE_LIMITING.md)
* [Supabase RLS Audit](RLS_AUDIT.md)
* [Security Audit](SECURITY_AUDIT.md)

## Frontend

Install dependencies:

```bash
cd frontend
cp .env.example .env
npm install
```

Run the frontend:

```bash
cd frontend
npm run dev
```

Open:

```text
http://localhost:5173
```

The Vite dev server proxies `/api` requests to `http://localhost:8000` when `VITE_API_BASE_URL` is empty.

Build and lint:

```bash
cd frontend
npm run build
npm run lint
```

## Backend Local Development

Install dependencies:

```bash
cd backend
cp .env.example .env
uv sync
```

Start PostgreSQL only:

```bash
cd ..
docker compose up -d postgres
```

Apply migrations:

```bash
cd backend
uv run alembic upgrade head
```

Seed demo data:

```bash
cd backend
uv run python -m app.seed
```

Run the API locally:

```bash
cd backend
uv run fastapi dev app/main.py
```

### Test Real MCP Discovery Locally

Start a compliant MCP server with a Streamable HTTP or SSE endpoint, then configure the backend:

```env
MCP_DISCOVERY_MODE=real
ALLOW_PRIVATE_MCP_URLS=true
```

For an authenticated server, store the credential in a backend-only environment variable:

```env
MCP_AUTH_LOCAL_DEMO=replace-with-the-local-server-token
```

Register the server through the MCP Servers page or API:

```json
{
  "name": "Local MCP Demo",
  "server_url": "http://127.0.0.1:9000/mcp",
  "transport_type": "streamable_http",
  "auth_type": "bearer",
  "auth_secret_ref": "MCP_AUTH_LOCAL_DEMO",
  "request_timeout_seconds": 30,
  "connect_timeout_seconds": 10
}
```

Run sync from AgentHQ. A successful sync creates or reuses the linked agent and imports discovered
tool names and descriptions. Never place credentials in `server_url`.

Run backend checks:

```bash
cd backend
uv run pytest
uv run ruff check .
uv run mypy app tests
```

Create migrations:

```bash
cd backend
uv run alembic revision --autogenerate -m "describe change"
```

## Demo Flow

1. Start Docker services.
2. Seed demo data.
3. Open the frontend at `http://localhost:5173`.
4. Review the Dashboard summary cards.
5. Open Agents and inspect tools for the Payment Operations Agent.
6. Use Policy Decision Tester with a high-risk action.
7. Create a simulated high-risk execution and observe policy enforcement.
8. Approve a pending approval.
9. Create or resolve an incident.
10. Review Compliance summary and incident report.

See [DEMO.md](DEMO.md) for curl-based examples.

## Screenshots

Screenshots can be added here once the visual demo flow stabilizes:

* Dashboard overview
* Agent detail and tools
* Policy decision tester
* Compliance summary

## Roadmap

### Completed

* Organizations
* Memberships
* Organization Bootstrap
* Organization Invitations
* Invite Acceptance
* Tenant Isolation
* Tenant-Aware UX
* Audit Logs UI
* MCP Server Registration
* MCP Tool Discovery
* Linked Agent Creation
* Tool Sync Auditing
* Authentication & RBAC
* JWT Authentication
* User Management
* Agent Ownership Enforcement
* Governance Workflows
* Compliance Reporting
* Performance Hardening
* Pagination
* Database Indexing
* Dashboard Optimization
* Compliance Optimization
* Atomic Transactions
* Rollback Testing
* Failure Handling
* Organization Authorization Hardening
* Security Event Trails
* Audit Redaction
* MCP URL and Error Hardening
* Centralized Rate Limiting
* Supabase RLS Lockdown
* Real MCP Protocol Integration

### Upcoming

* Foundry Agent Registration
* Copilot Studio Agent Registration
* Cost Tracking
* Notifications
* Organization Switching
* SSO

## Health Check

```bash
curl http://localhost:8000/health
```
