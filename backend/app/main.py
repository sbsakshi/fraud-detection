import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from . import models  # noqa: F401  (registers ORM mappers at startup)
from .config import settings
from .db import SessionLocal, check_db_connection
from .graph.live_graph import rebuild_transaction_graph
from .ml import get_models
from .ml.model_loader import ModelsNotTrainedError
from .routers import accounts, cases, graph, stats, transactions

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Load once at startup, not per-request. A missing/untrained model
    # doesn't stop the app from serving its health check -- POST
    # /transactions just 503s until someone runs `python -m ml.train`.
    try:
        get_models()
        logger.info("ML models loaded from ml/models/")
    except ModelsNotTrainedError as exc:
        logger.warning("ML models not loaded: %s", exc)

    if settings.rebuild_graph_on_startup:
        try:
            with SessionLocal() as db:
                count = rebuild_transaction_graph(db)
            logger.info("Rebuilt in-memory transaction graph from %d persisted transactions", count)
        except Exception as exc:  # DB down or not migrated yet: serve /health, which reports it
            logger.warning("Could not rebuild transaction graph at startup: %s", exc)
    yield


app = FastAPI(title="Finsight Fraud Intelligence", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["X-Total-Count"],  # list endpoints report the unpaged match count here
)

app.include_router(accounts.router)
app.include_router(transactions.router)
app.include_router(graph.router)
app.include_router(cases.router)
app.include_router(stats.router)


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


@app.get("/health/live")
def liveness() -> dict:
    """The process is up and serving requests. Never touches the DB or the models."""
    return {"status": "alive"}


@app.get("/health/ready")
def readiness() -> dict:
    """Ready to score: the database answers *and* the ML artifacts are loaded.

    `/health` reports a missing model as a field and still returns 200; an
    orchestrator needs a hard failure instead, because `POST /transactions`
    returns 503 until the models load.
    """
    try:
        check_db_connection()
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"database unavailable: {exc}") from exc
    try:
        get_models()
    except ModelsNotTrainedError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return {"status": "ready"}
