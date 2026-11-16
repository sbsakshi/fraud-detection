# Finsight

A synthetic UPI fraud-intelligence system: rules + ML + graph analysis score
every transaction in real time, cluster mule rings, and drive a
proportionate intervention instead of an outright freeze. Runs entirely
against synthetic accounts and transactions.

**New here?** Read the [developer guide](docs/DEVELOPER_GUIDE.md): architecture, every
component, the ML models, cases, accuracy, design decisions and known gaps.

## Status

- `backend/`: FastAPI scoring service. Rules, a calibrated XGBoost model and
  graph analysis score each transaction, then fusion picks one of six
  interventions and opens a case for the severe ones. Investigators confirm
  fraud via `POST /cases/{id}/confirm-fraud`. See
  [backend/README.md](backend/README.md).
- `frontend/`: Vite + React dashboard with the live transaction feed, stat
  tiles and money-movement network graph. It falls back to demo data when the
  backend is empty or unreachable.
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

To fill the dashboard with scored synthetic traffic once the stack is up:

```bash
cd backend && python scripts/replay_synthetic.py --limit 2000
```

To regenerate the data and retrain (see [ml/README.md](ml/README.md)):

```bash
python -m ml.synthetic.generate_dataset
python -m ml.features.build_features
python -m ml.train
```
