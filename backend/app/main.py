from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from . import models  # noqa: F401  (registers ORM mappers at startup)
from .config import settings
from .db import check_db_connection

app = FastAPI(title="Finsight Fraud Intelligence")

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
    return {"status": "ok", "service": "finsight-backend"}
