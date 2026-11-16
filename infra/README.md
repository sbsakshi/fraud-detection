# infra

Local orchestration lives in `docker-compose.yml` at the repo root, and CI in
`.github/workflows/ci.yml`.

## Running it

```bash
docker compose up --build                     # production-style: nginx serves the built dashboard
docker compose -f docker-compose.yml -f docker-compose.dev.yml up --build   # hot-reload Vite server
```

| Service | Image | Port | Health |
|---|---|---|---|
| `postgres` | `postgres:16-alpine`, named volume | 5432 | `pg_isready` |
| `backend` | `backend/Dockerfile`, built from the repo root so `ml/models/` sits beside `backend/` | 8000 | `GET /health/ready` (60s start period) |
| `frontend` | `frontend/Dockerfile` target `prod`: Vite build served by nginx (SPA fallback, immutable caching for `/assets`) | 5173 -> 80 | nginx `wget` check |

The frontend waits for the backend to be healthy. `/health/ready` returns 503
until the database answers **and** the ML artifacts are loaded, which is the
moment `POST /transactions` can score. `/health/live` only says the process is up
(for liveness probes), and the older `/health` still reports a missing model as a
field with a 200. The dev override needs Docker Compose 2.24+ (`!override`).

`VITE_API_BASE_URL` is baked into the production bundle at build time (it is the
address the *browser* uses), so changing it means rebuilding the frontend image.

## Configuration

Runtime-tunable configuration sits next to the code that reads it. These are read
once at startup, so a change needs a backend restart but not a code change:

- `backend/app/scoring/intervention_config.json`: the intervention ladder and the
  fusion weights. Tuned together by `backend/scripts/tune_fusion.py`. Its content
  hash is stored on every score as `ladder_version`.
- `backend/app/rules/config.py` and `backend/app/graph/config.py`: rule and graph thresholds.
- `ml/models/model_metadata.json`: the anomaly-reason percentile, written by
  `python -m ml.train`. It also records an `alert_threshold`, but that is a
  reporting number for the training report; the backend does not read it. Its
  `trained_at` is stored on every score as `model_version`.

Environment: copy `.env.example` to `.env` (gitignored) to set the Postgres
credentials, the allowed CORS origins and the API URL the dashboard uses.
Compose falls back to local-dev defaults when `.env` is absent. The backend
reads `DATABASE_URL`, `CORS_ORIGINS` and `REBUILD_GRAPH_ON_STARTUP` from its
environment (`backend/app/config.py`).

## Database

Postgres uses Alembic (`alembic upgrade head`, run by the compose backend
command). The zero-install SQLite path (`backend/scripts/dev.sh`) uses
`create_all` instead; an existing SQLite file does not pick up new columns, so
reset it with `dev.sh --reset` or `ALTER TABLE` by hand. Migrations:

| Revision | Change |
|---|---|
| `c190bb280894` | initial schema |
| `a7d3e1f4b2c9` | `risk_scores.model_version`, `risk_scores.ladder_version` (nullable; older rows have none) |

CI runs `alembic check`, which fails if the models drift from the migrations.

The backend's in-memory transaction graph is rebuilt from the `transactions`
table at startup, so restarts keep every account's graph history.

## CI (`.github/workflows/ci.yml`)

| Job | What it checks |
|---|---|
| `ml` | ML unit tests, including the graph-feature tests |
| `backend` | Backend unit suite on in-memory SQLite (rebuilds `features.csv` first) |
| `backend-postgres` | Applies the migrations to a real Postgres 16, runs `alembic check`, then an end-to-end test of scoring, filters, aggregates, cases and the fraud-confirmation feedback loop |
| `frontend` | `npm ci` and the production build |
| `images` | `docker compose config`, builds both images, loads the ML artifacts inside the backend image, and checks the frontend image serves the app shell for client-side routes |

## Not yet handled

- A secrets manager for production credentials.
- Running more than one backend replica: the live transaction graph is
  process-local, so each replica would score against a different graph.
- Authentication on the API, and metrics/tracing.
- Postgres backups.
- The `backend-postgres` and `images` jobs were written without a local Postgres
  or Docker available; their first CI run is the first time they execute there.
