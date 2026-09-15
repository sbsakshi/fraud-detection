import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from . import models  # noqa: F401  (registers ORM mappers at startup)
from .config import settings
from .db import check_db_connection
from .ml import get_models
from .ml.model_loader import ModelsNotTrainedError

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Load once at startup, not per-request (Phase 6 is the first thing that
    # actually calls score_transaction). A missing/untrained model doesn't
    # stop the app from serving its health check -- it's just not scored yet.
    try:
        get_models()
        logger.info("ML models loaded from ml/models/")
    except ModelsNotTrainedError as exc:
        logger.warning("ML models not loaded: %s", exc)
    yield


app = FastAPI(title="Finsight Fraud Intelligence", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
def health_check() -> dict:
    try:
        check_db_connection()
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"database unavailable: {exc}") from exc

    try:
        get_models()
        ml_models_status = "loaded"
    except ModelsNotTrainedError:
        ml_models_status = "not_trained"

    return {"status": "ok", "service": "finsight-backend", "ml_models": ml_models_status}
