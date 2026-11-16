# Finsight

A synthetic UPI fraud-intelligence system: rules + ML + graph analysis score
every transaction in real time, cluster mule rings, and drive a
proportionate intervention instead of an outright freeze. Runs entirely
against synthetic accounts and transactions.

**New here?** Read the [developer guide](docs/DEVELOPER_GUIDE.md): architecture, every
component, the ML models, cases, accuracy, design decisions and known gaps.
The [ML model card](docs/ml-model-card.html) summarises the model, its data and
its evaluation.

## Status

- `backend/`: FastAPI scoring service. Rules, a calibrated XGBoost model and
  graph analysis score each transaction, then fusion picks one of six
  interventions and opens a case for the severe ones. Fusion weights and the
  intervention ladder live in one config file
  (`app/scoring/intervention_config.json`), tuned offline by
  `scripts/tune_fusion.py`; every risk score records the config version that
  produced it. `/stats/*` endpoints feed the overview page. Investigators add
  notes, close cases or confirm fraud via `POST /cases/{id}/confirm-fraud`.
  See [backend/README.md](backend/README.md).
- `frontend/`: Vite + React dashboard (served by nginx in Docker) with an
  overview/analytics page, live transaction feed, case queue and case detail
  workflow, account profiles, money-movement network graph and a guided demo
  page. It falls back to demo data when the backend is empty or unreachable.
- `ml/`: synthetic data generator (with burn-in, legitimate look-alikes and
  no label shortcuts), feature engineering, and `python -m ml.train` for
  training, calibration and honest evaluation. See [ml/README.md](ml/README.md).
- CI (`.github/workflows/ci.yml`) runs the ML tests, the backend tests, the
  backend tests against a real Postgres, the frontend build, and the Docker
  images. See [infra/README.md](infra/README.md).

## Run locally

```bash
docker compose up --build
```

Then:

- Backend health: http://localhost:8000/health/ready
- Frontend: http://localhost:5173
- Postgres: localhost:5432

For a hot-reloading frontend, add the dev override:

```bash
docker compose -f docker-compose.yml -f docker-compose.dev.yml up --build
```

Without Docker, run the backend against SQLite (needs `backend/.venv`):

```bash
backend/scripts/dev.sh           # API on :8000
backend/scripts/dev.sh --reset   # wipe the local finsight.db first
```

To fill the dashboard with scored synthetic traffic once the stack is up:

```bash
cd backend && python scripts/replay_dataset.py --limit 5000                       # backfill history
cd backend && python scripts/replay_dataset.py --offset 5000 --limit 500 --rate 5 --shift-to-now   # live trickle
```

`--shift-to-now` moves timestamps so the newest transaction is "now" and the
recent-activity views fill up. `scripts/replay_synthetic.py --limit 2000` is
the simpler replayer.

To regenerate the data and retrain (see [ml/README.md](ml/README.md)):

```bash
python -m ml.synthetic.generate_dataset
python -m ml.features.build_features
python -m ml.train
cd backend && python scripts/tune_fusion.py   # retune fusion weights + ladder
```
