# Finsight

A synthetic UPI fraud-intelligence system: rules + ML + graph analysis score
every transaction in real time, cluster mule rings, and drive a
proportionate intervention instead of an outright freeze. Runs entirely
against synthetic accounts and transactions.

## Phase 1 foundation

This repository contains the monorepo structure and the Phase 1 foundation:

- `backend/` FastAPI service (health check only so far) with SQLAlchemy
  models and an Alembic migration for the full schema: `accounts`,
  `transactions`, `risk_scores`, `reason_codes`, `graph_edges`, `cases`,
  `case_events`.
- `frontend/` Vite + React + TypeScript shell; real dashboards land in
  Phase 7.
- `ml/` research and notebook artifacts workspace (Phase 4).
- `infra/` deployment and environment infrastructure (later phases).

## Run locally

```bash
docker compose up --build
```

Then:

- Backend health: http://localhost:8000/health
- Frontend: http://localhost:5173
- Postgres: localhost:5432
