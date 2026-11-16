#!/usr/bin/env bash
# Run the backend locally against SQLite -- no Docker or Postgres needed.
#
#   backend/scripts/dev.sh            # start the API on :8000
#   backend/scripts/dev.sh --reset    # wipe finsight.db first
#
# DATABASE_URL can still be overridden to point at Postgres.
set -euo pipefail
cd "$(dirname "$0")/.."

# xgboost on macOS needs libomp, normally from Homebrew. scikit-learn's wheel
# bundles a copy, so fall back to that when Homebrew's isn't installed.
SKLEARN_LIBS="$(.venv/bin/python -c 'import sklearn,os;print(os.path.join(os.path.dirname(sklearn.__file__),".dylibs"))')"
export DYLD_FALLBACK_LIBRARY_PATH="${SKLEARN_LIBS}${DYLD_FALLBACK_LIBRARY_PATH:+:$DYLD_FALLBACK_LIBRARY_PATH}"

export DATABASE_URL="${DATABASE_URL:-sqlite:///$PWD/finsight.db}"
if [[ "${1:-}" == "--reset" ]]; then rm -f finsight.db; fi

export PYTHONPATH="$PWD"
.venv/bin/python scripts/init_local_db.py
exec .venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8000
