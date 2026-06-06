# AgentHQ Deployment

This guide deploys AgentHQ with Supabase PostgreSQL, a Render backend, and a Vercel frontend.

## Required Environment Variables

Backend:

| Variable | Example | Notes |
| --- | --- | --- |
| `DATABASE_URL` | `postgresql://postgres.project-ref:password@aws-0-region.pooler.supabase.com:5432/postgres?sslmode=require` | Supabase PostgreSQL connection string. AgentHQ automatically selects the psycopg 3 SQLAlchemy driver. |
| `BACKEND_CORS_ORIGINS` | `https://agenthq.example.com,https://agenthq-git-main-team.vercel.app` | Comma-separated exact frontend origins. Do not use `*` in production. |

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
2. In Render, create a Blueprint from the repository.
3. Set the secret environment variables:
   * `DATABASE_URL`: Supabase connection string
   * `BACKEND_CORS_ORIGINS`: exact Vercel production URL and any approved preview/custom domains
4. Deploy the `agenthq-api` web service.
5. Confirm `https://<service>.onrender.com/health` returns a successful response.

The container runs `alembic upgrade head` before starting Uvicorn and binds to Render's injected `PORT`.

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
* Configure exact HTTPS CORS origins; do not use wildcard origins.
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
