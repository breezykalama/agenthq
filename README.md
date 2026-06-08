# AgentHQ

Enterprise AI Agent Governance Platform.

AgentHQ provides visibility, governance, approvals, policy enforcement, execution tracking, incident management, auditability, and compliance reporting for AI agents.

## Live Demo

Frontend:
[https://agenthq-seven.vercel.app/](https://agenthq-seven.vercel.app/)

Backend API:
[https://agenthq.onrender.com/docs](https://agenthq.onrender.com/docs)

## Current Version

AgentHQ v0.3.2

## Project Status

AgentHQ is a live Enterprise AI Agent Governance Platform focused on:

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

## Architecture

![AgentHQ Architecture](docs/images/agenthq-architecture.png)

AgentHQ uses a React frontend for the governance console, a FastAPI backend for API workflows, modular governance services for policy decisions and lifecycle rules, PostgreSQL persistence for operational records, and audit/compliance capabilities for reporting and review.

The architecture now includes a JWT authentication layer, reusable RBAC enforcement layer, MCP Server Registry, and MCP Discovery Layer that synchronizes discovered tools into the governance layer.

## Core Capabilities

* **Agent Registry**: Maintain a catalog of governed agents, ownership, status, department, and risk level.
* **Policy Enforcement**: Evaluate active policy rules to allow, require approval, or block requested actions.
* **Approval Workflows**: Track human approval requests for high-risk or policy-controlled actions.
* **Execution Tracking**: Record simulated agent actions, status, cost, latency, policy decisions, and outcomes.
* **Incident Management**: Capture and resolve incidents related to failed executions, blocked actions, or policy violations.
* **Audit Logging**: Preserve structured before/after audit events across governance workflows.
* **Compliance Reporting**: Generate read-only summaries for auditors and managers.
* **MCP Server Registration**: Register MCP servers and track connection, synchronization, and error status.
* **MCP Tool Discovery**: Discover tools through an adapter-based integration and sync them into the Agent Tools Registry.
* **Linked Agent Creation**: Automatically create or reuse the governed agent associated with an MCP server.
* **Tool Sync Auditing**: Record successful and failed MCP synchronization events with before/after snapshots.

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

## Quality

* 201 automated tests passing
* Ruff clean
* MyPy clean
* Dockerized deployment
* Live deployment
* Supabase PostgreSQL
* Render backend
* Vercel frontend
* Atomic transaction safety
* Query-count regression tests
* Seed/demo data included

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
Backend:  DATABASE_URL, BACKEND_CORS_ORIGINS
Frontend: VITE_API_BASE_URL
```

Use exact HTTPS origins in `BACKEND_CORS_ORIGINS`, keep `DATABASE_URL` in backend secret storage, apply migrations before serving a new version, and never seed production automatically. FastAPI interactive docs remain enabled for this MVP and can be restricted at the edge when needed.

See [DEPLOYMENT.md](DEPLOYMENT.md) for the complete deployment guide.

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

Completed in v0.2.0:

* MCP Server Registration
* MCP Tool Discovery
* Linked Agent Creation
* Tool Sync Auditing

Completed in v0.3.0:

* Authentication & RBAC
* JWT Authentication
* User Management
* Agent Ownership Enforcement

### Completed Hardening

* Pagination
* Database Indexing
* Dashboard Optimization
* Compliance Optimization
* Atomic Transactions
* Rollback Testing
* Failure Handling

### Upcoming

* Real MCP Protocol Integration
* Foundry Agent Registration
* Copilot Studio Agent Registration
* Cost Tracking
* Notifications
* Multi-tenancy

## Health Check

```bash
curl http://localhost:8000/health
```
