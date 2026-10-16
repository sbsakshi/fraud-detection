# infra

Local orchestration lives in `docker-compose.yml` at the repo root, and CI in
`.github/workflows/ci.yml`. Runtime-tunable configuration sits next to the
code that reads it, so it can be changed without a code change:

- `backend/app/scoring/intervention_config.json`: the intervention ladder.
- `backend/app/rules/config.py` and `backend/app/graph/config.py`: rule and graph thresholds.
- `ml/models/model_metadata.json`: the ML alert threshold and anomaly-reason percentile, written by `python -m ml.train`.

Environment: copy `.env.example` to `.env` (gitignored) to set the Postgres
credentials, the allowed CORS origins and the API URL the dashboard uses.
Compose falls back to local-dev defaults when `.env` is absent. The backend
reads `DATABASE_URL`, `CORS_ORIGINS` and `REBUILD_GRAPH_ON_STARTUP` from its
environment (`backend/app/config.py`).

The backend's in-memory transaction graph is rebuilt from the `transactions`
table at startup, so restarts keep every account's graph history.

Not yet handled here: a secrets manager for production credentials, and a
production frontend image (the container runs the Vite dev server).
