# infra

Local orchestration lives in `docker-compose.yml` at the repo root, and CI in
`.github/workflows/ci.yml`. Runtime-tunable configuration sits next to the
code that reads it, so it can be changed without a code change:

- `backend/app/scoring/intervention_config.json`: the intervention ladder.
- `backend/app/rules/config.py` and `backend/app/graph/config.py`: rule and graph thresholds.
- `ml/models/model_metadata.json`: the ML alert threshold and anomaly-reason percentile, written by `python -m ml.train`.

Not yet handled here: secrets management (database credentials and the CORS
origin are hard-coded for local use), a production frontend image (the
container runs the Vite dev server), and rebuilding the backend's in-memory
transaction graph from `graph_edges` after a restart.
