"""End-to-end tests for the Phase 6 scoring endpoint: real rules, real
trained models (the committed ml/models/ artifacts), real graph engine --
only the database is swapped for an isolated in-memory SQLite instance per
test, and the process-wide in-memory transaction graph is reset around
each one so tests can't see each other's history.
"""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db import get_db
from app.graph.live_graph import reset_transaction_graph
from app.main import app
from app.models import Base

ACCEPTABLE_LEVELS = {"inform", "warn", "verify", "hold", "restrict", "escalate"}
CASE_OPENING_LEVELS = {"restrict", "escalate"}


@pytest.fixture()
def client():
    # StaticPool: a plain sqlite:///:memory: engine hands out a *new*, empty
    # in-memory database per connection, so a session that didn't happen to
    # reuse the exact connection create_all ran on would see no tables at
    # all. StaticPool keeps everyone on the one connection.
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    TestingSession = sessionmaker(bind=engine)

    def override_get_db():
        db = TestingSession()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db
    reset_transaction_graph()
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()
    reset_transaction_graph()
    engine.dispose()


def create_account(client: TestClient, upi_id: str, **overrides) -> dict:
    payload = {
        "upi_id": upi_id,
        "account_number": f"ACC-{upi_id}",
        "ifsc_code": "TEST0000001",
        "owner_name": "Test Owner",
        "bank_name": "Test Bank",
        **overrides,
    }
    resp = client.post("/accounts", json=payload)
    assert resp.status_code == 201, resp.text
    return resp.json()


def score(client: TestClient, sender: str, receiver: str, amount: str, device_id: str, **overrides) -> dict:
    payload = {
        "sender_upi_id": sender,
        "receiver_upi_id": receiver,
        "amount": amount,
        "device_id": device_id,
        **overrides,
    }
    resp = client.post("/transactions", json=payload)
    assert resp.status_code == 201, resp.text
    return resp.json()


def assert_case_invariant(body: dict) -> None:
    level = body["risk_score"]["intervention_level"]
    assert level in ACCEPTABLE_LEVELS
    if level in CASE_OPENING_LEVELS:
        assert body["case"] is not None
        assert body["case"]["status"] in {"open", "escalated"}
    else:
        assert body["case"] is None


def test_create_account(client: TestClient):
    account = create_account(client, "alice@bank")
    assert account["upi_id"] == "alice@bank"
    assert account["account_type"] == "individual"
    assert "id" in account


def test_duplicate_account_upi_returns_409(client: TestClient):
    create_account(client, "alice@bank")
    resp = client.post(
        "/accounts",
        json={
            "upi_id": "alice@bank", "account_number": "X", "ifsc_code": "Y", "owner_name": "Z", "bank_name": "W",
        },
    )
    assert resp.status_code == 409


def test_transaction_requires_existing_accounts(client: TestClient):
    resp = client.post(
        "/transactions",
        json={"sender_upi_id": "ghost@bank", "receiver_upi_id": "also_ghost@bank", "amount": "100.00", "device_id": "d1"},
    )
    assert resp.status_code == 404


def test_score_a_plain_first_transaction(client: TestClient):
    create_account(client, "alice@bank", device_id="d1")
    create_account(client, "bob@bank", device_id="d2")

    body = score(client, "alice@bank", "bob@bank", "100.00", "d1")
    assert body["sender_upi_id"] == "alice@bank"
    assert 0.0 <= body["risk_score"]["fused_score"] <= 1.0
    assert 0.0 <= body["risk_score"]["confidence"] <= 1.0
    assert len(body["reason_codes"]) >= 0  # a quiet first transaction may have none at all
    assert_case_invariant(body)


def test_case_invariant_holds_across_an_account_takeover_shaped_sequence(client: TestClient):
    create_account(client, "alice@bank", device_id="d1")
    for i in range(8):
        create_account(client, f"friend{i}@bank", device_id=f"df{i}")
    create_account(client, "stranger@bank", device_id="ds")

    # Build up an established, boring baseline for alice.
    for i in range(8):
        body = score(client, "alice@bank", f"friend{i}@bank", "100.00", "d1")
        assert_case_invariant(body)

    # Then an out-of-character payment: a brand-new device, a huge amount,
    # to someone alice has never paid -- exactly what
    # amount_above_historical_average + first_time_beneficiary + the ML
    # model's amount_zscore_sender feature are all built to catch.
    body = score(client, "alice@bank", "stranger@bank", "50000.00", "brand-new-device")
    assert_case_invariant(body)
    reason_sources = {rc["source"] for rc in body["reason_codes"]}
    # At least one signal source should have something to say about this.
    assert reason_sources  # non-empty


def test_transaction_response_reason_codes_have_the_shared_shape(client: TestClient):
    create_account(client, "alice@bank", device_id="d1")
    for i in range(8):
        create_account(client, f"friend{i}@bank", device_id=f"df{i}")
    for i in range(8):
        score(client, "alice@bank", f"friend{i}@bank", "100.00", "d1")

    body = score(client, "alice@bank", "friend0@bank", "50000.00", "new-device")
    for rc in body["reason_codes"]:
        assert rc["source"] in {"rule", "ml", "graph"}
        assert isinstance(rc["template"], str) and rc["template"]
        assert isinstance(rc["details"], dict)


def test_list_transactions_is_empty_before_any_scoring(client: TestClient):
    resp = client.get("/transactions")
    assert resp.status_code == 200
    assert resp.json() == []


def test_list_transactions_returns_newest_first(client: TestClient):
    create_account(client, "alice@bank", device_id="d1")
    create_account(client, "bob@bank", device_id="d2")

    first = score(client, "alice@bank", "bob@bank", "100.00", "d1")
    second = score(client, "alice@bank", "bob@bank", "200.00", "d1")

    resp = client.get("/transactions")
    assert resp.status_code == 200
    body = resp.json()
    assert len(body) == 2
    assert body[0]["transaction_id"] == second["transaction_id"]
    assert body[1]["transaction_id"] == first["transaction_id"]
    assert_case_invariant(body[0])
    assert_case_invariant(body[1])


def test_list_transactions_respects_limit(client: TestClient):
    create_account(client, "alice@bank", device_id="d1")
    create_account(client, "bob@bank", device_id="d2")
    for _ in range(5):
        score(client, "alice@bank", "bob@bank", "100.00", "d1")

    resp = client.get("/transactions", params={"limit": 2})
    assert resp.status_code == 200
    assert len(resp.json()) == 2


def test_stats_before_any_scoring_are_all_zero(client: TestClient):
    resp = client.get("/transactions/stats")
    assert resp.status_code == 200
    assert resp.json() == {
        "transactions_scored": 0,
        "flagged_rate": 0.0,
        "active_cases": 0,
        "avg_fused_score": 0.0,
    }


def test_graph_snapshot_is_empty_before_any_scoring(client: TestClient):
    resp = client.get("/graph")
    assert resp.status_code == 200
    assert resp.json() == {"nodes": [], "edges": []}


def test_graph_snapshot_reflects_scored_transactions(client: TestClient):
    create_account(client, "alice@bank", device_id="d1")
    create_account(client, "bob@bank", device_id="d2")
    create_account(client, "charlie@bank", device_id="d3")
    score(client, "alice@bank", "bob@bank", "100.00", "d1")
    # bob transacting from the *same device string* alice already used is
    # what TransactionGraph.add_transaction keys shared_device edges on
    # (app/graph/builder.py's `device_users` index) -- an account's own
    # `device_id` column is unrelated to that.
    score(client, "bob@bank", "charlie@bank", "50.00", "d1")

    resp = client.get("/graph")
    assert resp.status_code == 200
    body = resp.json()

    node_ids = {n["id"] for n in body["nodes"]}
    assert node_ids == {"alice@bank", "bob@bank", "charlie@bank"}
    for node in body["nodes"]:
        assert isinstance(node["community"], int)

    edge_types = {e["type"] for e in body["edges"]}
    assert "transaction" in edge_types
    assert "shared_device" in edge_types
    txn_edge = next(e for e in body["edges"] if e["type"] == "transaction" and e["source"] == "alice@bank")
    assert txn_edge["target"] == "bob@bank"
    assert txn_edge["weight"] == 1.0


def test_graph_snapshot_aggregates_repeated_transaction_edges(client: TestClient):
    create_account(client, "alice@bank", device_id="d1")
    create_account(client, "bob@bank", device_id="d2")
    for _ in range(3):
        score(client, "alice@bank", "bob@bank", "100.00", "d1")

    resp = client.get("/graph")
    assert resp.status_code == 200
    body = resp.json()

    txn_edges = [e for e in body["edges"] if e["type"] == "transaction"]
    assert len(txn_edges) == 1  # collapsed into one edge, not one per transaction
    assert txn_edges[0]["weight"] == 3.0


def test_stats_reflect_scored_transactions_and_open_cases(client: TestClient):
    create_account(client, "alice@bank", device_id="d1")
    for i in range(8):
        create_account(client, f"friend{i}@bank", device_id=f"df{i}")
    create_account(client, "stranger@bank", device_id="ds")

    for i in range(8):
        score(client, "alice@bank", f"friend{i}@bank", "100.00", "d1")
    escalation = score(client, "alice@bank", "stranger@bank", "50000.00", "brand-new-device")

    resp = client.get("/transactions/stats")
    assert resp.status_code == 200
    stats = resp.json()
    assert stats["transactions_scored"] == 9
    assert 0.0 <= stats["flagged_rate"] <= 1.0
    assert 0.0 <= stats["avg_fused_score"] <= 1.0
    if escalation["case"] is not None:
        assert stats["active_cases"] >= 1
