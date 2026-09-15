FROM python:3.12-slim

# Repo root, not backend/ -- see docker-compose.yml's build context for this
# service. app/ml/model_loader.py resolves ml/models/*.joblib via a relative
# path (parents[3] from the file), the same relative layout as a native
# checkout (backend/ and ml/ as siblings), so that path keeps working
# unchanged whether this image or a local `uvicorn app.main:app` is running.
WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

COPY backend/requirements.txt ./backend/requirements.txt
RUN pip install --no-cache-dir -r backend/requirements.txt

COPY backend/ ./backend/
# Only the trained artifacts -- not ml/data (large CSVs), ml/notebooks, or
# ml/synthetic, none of which the running app needs.
COPY ml/models/ ./ml/models/

WORKDIR /app/backend
EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
