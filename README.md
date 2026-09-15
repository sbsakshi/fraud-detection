# Finsight

A synthetic UPI fraud-intelligence system: rules + ML + graph analysis score
every transaction in real time, cluster mule rings, and drive a
proportionate intervention instead of an outright freeze. Runs entirely
against synthetic accounts and transactions.

## Status

- `backend/` — Phase 1 foundation done (FastAPI health check, SQLAlchemy
  models + Alembic migration for the full schema: `accounts`,
  `transactions`, `risk_scores`, `reason_codes`, `graph_edges`, `cases`,
  `case_events`). Phase 3 rule engine, Phase 4 ML model loading, and
  Phase 5 graph intelligence (mule-collector detection, shared-device and
  repeated-counterparty checks, fraud-cluster exposure, money-trail
  tracing) all done — see [backend/README.md](backend/README.md). No
  scoring endpoint yet; that's Phase 6, wiring rules + ML + graph into one
  fused score.
- `frontend/` — Vite + React + TypeScript shell; real dashboards land in
  Phase 7.
- `ml/` — Phase 2 synthetic data generator and Phase 4 model training
  (XGBoost, Random Forest, Isolation Forest + SHAP) done — see
  [ml/README.md](ml/README.md).
- `infra/` — deployment and environment infrastructure (later phases).

## Run locally

```bash
docker compose up --build
```

Then:

- Backend health: http://localhost:8000/health
- Frontend: http://localhost:5173
- Postgres: localhost:5432
