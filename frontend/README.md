# AgentHQ Frontend

React dashboard MVP for the AgentHQ backend.

## Setup

```bash
cd frontend
cp .env.example .env
npm install
```

By default, the Vite dev server proxies `/api` calls to `http://localhost:8000`. Leave `VITE_API_BASE_URL` empty for local development, or set it to a backend origin when needed.

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
