import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from . import models  # noqa: F401  (registers ORM mappers at startup)
from .config import settings
from .db import check_db_connection
from .ml import get_models
from .ml.model_loader import ModelsNotTrainedError
from .routers import accounts, transactions

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Load once at startup, not per-request. A missing/untrained model
    # doesn't stop the app from serving its health check -- POST
    # /transactions just 503s until someone runs the training notebook.
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

app.include_router(accounts.router)
app.include_router(transactions.router)


@app.exception_handler(ModelsNotTrainedError)
async def models_not_trained_handler(request: Request, exc: ModelsNotTrainedError) -> JSONResponse:
    return JSONResponse(status_code=503, content={"detail": str(exc)})


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
