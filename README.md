# AgentHQ

AgentHQ is an enterprise agent governance platform MVP. It helps teams register agents, declare allowed tools, define policy rules, evaluate governance decisions, track simulated executions, manage approvals, record incidents, and produce compliance summaries.

## What AgentHQ Is

- A governance control plane for enterprise AI agents.
- A registry for agents, tools, policies, approvals, executions, incidents, audit logs, dashboards, and compliance reports.
- A local demo-ready backend and frontend for showing how governance workflows fit together.

## What AgentHQ Is Not

- It is not an authentication or identity system yet.
- It does not execute real agents or tools.
- It does not integrate with LLMs, MCP servers, or external AI providers yet.
- It is not production deployment infrastructure.

## Architecture Overview

```text
frontend/
  React + TypeScript + Vite + Tailwind
  React Router + TanStack Query + Axios

backend/
  FastAPI API
  SQLAlchemy models and repositories
  Service-layer business rules
  Alembic migrations
  PostgreSQL
```

Primary backend modules:

- Agent Registry
- Agent Tools Registry
- Policy Rules
- Policy Decision Engine
- Execution Tracking and Policy Enforcement
- Approvals
- Incident Reporting
- Audit Logging
- Dashboard and Compliance Reports

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
docker compose exec api agenthq-seed
```

Stop the stack:

```bash
docker compose down
```

Reset local database data:

```bash
docker compose down -v
```

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
uv run agenthq-seed
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

- Dashboard overview
- Agent detail and tools
- Policy decision tester
- Compliance summary

## Roadmap

- Authentication and role-based access control
- Production deployment configuration
- Real agent/tool execution integrations
- MCP and LLM provider integrations
- Richer compliance exports
- Deeper analytics and trend reporting

## Health Check

```bash
curl http://localhost:8000/health
```
