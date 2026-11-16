"""End-to-end checks against a real database, applied through the Alembic migrations.

The unit suite runs on in-memory SQLite, which cannot vouch for the Postgres
dialect (enum types, `NULLS LAST`, timezone-aware columns) or for the migration
chain matching the models. CI runs this file against a Postgres service:

    POSTGRES_TEST_URL=postgresql://finsight:finsight@localhost:5432/finsight_test \
        python -m pytest -m postgres tests/test_postgres_integration.py

Skipped when POSTGRES_TEST_URL is unset. The public schema is dropped and recreated
first, so the URL must point at a throwaway database whose name ends in `_test`.
"""

import os
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from app.db import get_db
from app.graph.live_graph import reset_transaction_graph
from app.main import app
from app.models.case import Case
from app.models.case_event import CaseEvent
from app.models.enums import CaseSeverity, CaseStatus

URL = os.getenv("POSTGRES_TEST_URL", "")
BACKEND_DIR = Path(__file__).resolve().parents[1]

pytestmark = [
    pytest.mark.postgres,
    pytest.mark.skipif(not URL, reason="POSTGRES_TEST_URL is not set"),
]


@pytest.fixture()
def env(monkeypatch):
    if URL.startswith("postgresql"):
        assert URL.split("?")[0].endswith("_test"), "refusing to reset a database not named *_test"
    engine = create_engine(URL, future=True)
    if URL.startswith("postgresql"):
        with engine.begin() as conn:
            conn.execute(text("DROP SCHEMA public CASCADE"))
            conn.execute(text("CREATE SCHEMA public"))

    monkeypatch.setenv("DATABASE_URL", URL)  # migrations/env.py reads this
    cfg = Config(str(BACKEND_DIR / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND_DIR / "migrations"))
    command.upgrade(cfg, "head")
    command.check(cfg)  # raises if the models have drifted from the migrations

    Session = sessionmaker(bind=engine)

    def override_get_db():
        db = Session()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db
    reset_transaction_graph()
    with TestClient(app) as client:
        yield client, Session
    app.dependency_overrides.clear()
    reset_transaction_graph()
    engine.dispose()


def _account(client, upi, device):
    resp = client.post(
        "/accounts",
        json={"upi_id": upi, "account_number": f"AC-{upi}", "ifsc_code": "TEST0000001",
              "owner_name": upi.split("@")[0].title(), "bank_name": "Test Bank", "device_id": device},
    )
    assert resp.status_code == 201, resp.text


def _pay(client, sender, receiver, amount, device):
    resp = client.post("/transactions", json={"sender_upi_id": sender, "receiver_upi_id": receiver,
                                              "amount": amount, "device_id": device})
    assert resp.status_code == 201, resp.text
    return resp.json()


def test_scoring_reads_cases_and_fraud_feedback_on_the_real_schema(env):
    client, Session = env
    for upi, device in [("alice@bank", "d1"), ("bob@bank", "d2"), ("carol@bank", "d3"), ("mallory@bank", "d4")]:
        _account(client, upi, device)

    scored = [_pay(client, "alice@bank", "bob@bank", f"{100 + i}.00", "d1") for i in range(6)]
    scored.append(_pay(client, "carol@bank", "bob@bank", "250.00", "d3"))
    for body in scored:
        assert body["risk_score"]["model_version"] and body["risk_score"]["ladder_version"]

    # Filters, paging header and the join-heavy listing query.
    listing = client.get("/transactions", params={"q": "alice", "has_case": "false", "limit": 3})
    assert listing.status_code == 200
    assert listing.headers["X-Total-Count"] == "6"
    assert len(listing.json()) == 3
    assert client.get("/transactions", params={"level": ["inform", "warn"]}).status_code == 200

    # Aggregates: tz-aware hourly bucketing, reason-code grouping, stats.
    buckets = client.get("/stats/timeseries", params={"hours": 3}).json()
    assert sum(b["total"] for b in buckets) == 7
    assert client.get("/stats/reason-codes").status_code == 200
    assert client.get("/transactions/stats").json()["transactions_scored"] == 7
    graph = client.get("/graph", params={"center": "bob@bank"}).json()
    assert {n["id"] for n in graph["nodes"]} >= {"alice@bank", "bob@bank", "carol@bank"}
    assert client.get("/accounts/bob@bank").json()["transactions_received"] == 7

    # Open a case on the first payment (what a RESTRICT decision does) and work it.
    first_id = scored[0]["transaction_id"]
    with Session() as db:
        case = Case(transaction_id=first_id, status=CaseStatus.OPEN, severity=CaseSeverity.HIGH)
        db.add(case)
        db.flush()
        db.add(CaseEvent(case_id=case.id, event_type="case_opened", description="test", actor="system"))
        db.commit()
        case_id = case.id

    queue = client.get("/cases").json()
    assert [c["id"] for c in queue] == [case_id]
    assert queue[0]["top_reason"]  # ORDER BY contribution DESC NULLS LAST
    assert client.get(f"/cases/{case_id}").json()["events"][0]["event_type"] == "case_opened"
    assert client.patch(f"/cases/{case_id}", json={"assigned_to": "priya", "actor": "priya"}).status_code == 200

    # Investigator confirmation feeds back into scoring for later payments to that receiver.
    assert client.post(f"/cases/{case_id}/confirm-fraud", json={"actor": "priya"}).status_code == 200
    after = _pay(client, "mallory@bank", "bob@bank", "100.00", "d4")
    codes = {rc["code"] for rc in after["reason_codes"]}
    assert "known_fraud_beneficiary" in codes
    assert after["risk_score"]["rule_score"] >= 0.9
    assert client.get("/accounts/bob@bank").json()["known_fraud"] is True
    assert client.post(f"/cases/{case_id}/close", json={"resolution": "fraud_confirmed", "actor": "priya"}).status_code == 200
