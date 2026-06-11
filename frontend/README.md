# AgentHQ Frontend

React and TypeScript governance console for AgentHQ.

The frontend supports organization bootstrap, invitation acceptance, tenant-aware navigation,
role-aware actions, MCP onboarding, policy testing, approvals, execution tracking, incidents,
compliance reports, and organization-scoped audit logs.

## Setup

```bash
cd frontend
cp .env.example .env
npm install
```

By default, the Vite dev server proxies `/api` calls to `http://localhost:8000`. Leave `VITE_API_BASE_URL` empty for local development, or set it to a backend origin when needed.

Authentication access tokens are stored in browser `localStorage` for the current MVP. The FastAPI
backend remains the authorization boundary; the frontend never sends a trusted `organization_id`.

## Production

Set the Vercel environment variable:

```text
VITE_API_BASE_URL=https://agenthq.onrender.com
```

Do not expose `DATABASE_URL`, `JWT_SECRET_KEY`, `BOOTSTRAP_SECRET`, or `REDIS_URL` to Vite.

## Run

```bash
npm run dev
```

Open:

```text
http://localhost:5173
```

## Build

```bash
npm run build
```

## Lint

```bash
npm run lint
```
