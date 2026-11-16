"""Case queue/detail/assign/note/close, transaction filters, and Overview stats.

Rows are seeded directly (not via POST /transactions) so each test controls
exactly which levels, scores and cases exist. Real scoring is covered in
test_transactions_api.py.
"""

from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient

from app.db import get_db
from app.main import app
from app.models.account import Account
from app.models.case import Case
from app.models.case_event import CaseEvent
from app.models.enums import (
    CaseSeverity,
    CaseStatus,
    InterventionLevel,
    ReasonCodeSource,
    TransactionStatus,
)
from app.models.reason_code import ReasonCode
from app.models.risk_score import RiskScore
from app.models.transaction import Transaction
from app.scoring.context_builders import get_known_fraud_upis

NOW = datetime.now(timezone.utc)


@pytest.fixture()
def api(db_session):
    app.dependency_overrides[get_db] = lambda: db_session
    try:
        with TestClient(app) as client:
            yield client
    finally:
        app.dependency_overrides.clear()


@pytest.fixture()
def seed(db_session, make_account):
    """seed(sender, receiver, score, level, case=(status, severity)|None, codes=[(source, code, contribution)], age_h=0)"""

    def _account(upi):
        return db_session.query(Account).filter_by(upi_id=upi).first() or make_account(upi, device_id=f"d-{upi}")

    def _seed(sender, receiver, score, level, case=None, codes=(), age_h=0.0, amount="1000.00"):
        s = _account(sender)
        r = _account(receiver)
        txn = Transaction(
            sender_account_id=s.id, receiver_account_id=r.id, amount=Decimal(amount), currency="INR",
            device_id=f"d-{sender}", transaction_type="P2P", status=TransactionStatus.COMPLETED,
            created_at=NOW - timedelta(hours=age_h),
        )
        db_session.add(txn)
        db_session.flush()
        rs = RiskScore(
            transaction_id=txn.id, rule_score=score, ml_score=score, graph_score=0.0,
            fused_score=score, confidence=0.9, intervention_level=level,
        )
        db_session.add(rs)
        db_session.flush()
        for source, code, contribution in codes:
            db_session.add(
                ReasonCode(
                    risk_score_id=rs.id, source=source, code=code, template=f"{code} fired", details={},
                    contribution=contribution,
                )
            )
        row = None
        if case:
            row = Case(transaction_id=txn.id, status=case[0], severity=case[1])
            db_session.add(row)
        db_session.commit()
        return txn, row

    return _seed


# --- transaction filters ----------------------------------------------------


def test_transaction_filters_and_total_count(api, seed):
    seed("a@b", "b@b", 0.05, InterventionLevel.INFORM)
    seed("c@b", "d@b", 0.60, InterventionLevel.HOLD, codes=[(ReasonCode and ReasonCodeSource.RULE, "fan_in_velocity", 0.4)])
    seed("e@b", "f@b", 0.95, InterventionLevel.ESCALATE, case=(CaseStatus.ESCALATED, CaseSeverity.CRITICAL))

    resp = api.get("/transactions")
    assert resp.status_code == 200 and resp.headers["X-Total-Count"] == "3"

    assert [t["risk_score"]["intervention_level"] for t in api.get("/transactions?level=hold&level=escalate").json()] == [
        "escalate", "hold",
    ]
    assert len(api.get("/transactions?min_score=0.5&max_score=0.7").json()) == 1
    assert len(api.get("/transactions?source=rule").json()) == 1
    assert len(api.get("/transactions?has_case=true").json()) == 1
    assert len(api.get("/transactions?has_case=false").json()) == 2
    assert [t["sender_upi_id"] for t in api.get("/transactions?q=E@B").json()] == ["e@b"]  # case-insensitive

    page = api.get("/transactions?limit=1&offset=1")
    assert len(page.json()) == 1 and page.headers["X-Total-Count"] == "3"


def test_transaction_time_filter(api, seed):
    seed("a@b", "b@b", 0.1, InterventionLevel.WARN, age_h=48)
    seed("c@b", "d@b", 0.1, InterventionLevel.WARN, age_h=1)
    since = (NOW - timedelta(hours=24)).isoformat()
    assert len(api.get("/transactions", params={"since": since}).json()) == 1


def test_transaction_detail_orders_reasons_by_contribution(api, seed):
    txn, _ = seed(
        "a@b", "b@b", 0.5, InterventionLevel.VERIFY,
        codes=[(ReasonCodeSource.RULE, "small", 0.1), (ReasonCodeSource.ML, "big", 0.4)],
    )
    body = api.get(f"/transactions/{txn.id}").json()
    assert [r["code"] for r in body["reason_codes"]] == ["big", "small"]
    assert api.get("/transactions/99999").status_code == 404


# --- case queue and detail --------------------------------------------------


def test_case_queue_orders_open_by_severity_then_age_closed_last(api, seed):
    _, old_high = seed("a1@b", "b1@b", 0.8, InterventionLevel.RESTRICT, case=(CaseStatus.OPEN, CaseSeverity.HIGH), age_h=5)
    _, new_crit = seed("a2@b", "b2@b", 0.95, InterventionLevel.ESCALATE, case=(CaseStatus.ESCALATED, CaseSeverity.CRITICAL), age_h=1)
    _, closed = seed("a3@b", "b3@b", 0.99, InterventionLevel.ESCALATE, case=(CaseStatus.CLOSED, CaseSeverity.CRITICAL), age_h=9)
    _, new_high = seed("a4@b", "b4@b", 0.8, InterventionLevel.RESTRICT, case=(CaseStatus.OPEN, CaseSeverity.HIGH), age_h=2)

    resp = api.get("/cases")
    assert [c["id"] for c in resp.json()] == [new_crit.id, old_high.id, new_high.id, closed.id]
    assert resp.headers["X-Total-Count"] == "4"
    assert [c["id"] for c in api.get("/cases?status=closed").json()] == [closed.id]
    assert len(api.get("/cases?severity=high").json()) == 2
    assert len(api.get("/cases?unassigned=true").json()) == 4


def test_case_queue_lists_top_reason(api, seed):
    seed(
        "a@b", "b@b", 0.9, InterventionLevel.ESCALATE, case=(CaseStatus.OPEN, CaseSeverity.CRITICAL),
        codes=[(ReasonCodeSource.RULE, "minor", 0.1), (ReasonCodeSource.GRAPH, "mule_collector_pattern", 0.6)],
    )
    assert api.get("/cases").json()[0]["top_reason"] == "mule_collector_pattern"


def test_case_detail_has_transaction_and_events(api, seed):
    _, case = seed("a@b", "b@b", 0.9, InterventionLevel.ESCALATE, case=(CaseStatus.ESCALATED, CaseSeverity.CRITICAL))
    api.post(f"/cases/{case.id}/notes", json={"actor": "ana", "note": "called the payer"})
    body = api.get(f"/cases/{case.id}").json()
    assert body["transaction"]["sender_upi_id"] == "a@b"
    assert [(e["event_type"], e["actor"]) for e in body["events"]] == [("note", "ana")]
    assert api.get("/cases/99999").status_code == 404


# --- mutations --------------------------------------------------------------


def test_assign_and_status_changes_leave_an_audit_trail(api, seed, db_session):
    _, case = seed("a@b", "b@b", 0.8, InterventionLevel.RESTRICT, case=(CaseStatus.OPEN, CaseSeverity.HIGH))
    resp = api.patch(f"/cases/{case.id}", json={"actor": "lead", "assigned_to": "ana", "status": "investigating"})
    assert resp.status_code == 200 and resp.json()["status"] == "investigating"

    detail = api.get(f"/cases/{case.id}").json()
    assert detail["assigned_to"] == "ana"
    assert [e["event_type"] for e in detail["events"]] == ["assigned", "status_changed"]

    api.patch(f"/cases/{case.id}", json={"actor": "lead", "unassign": True})
    assert api.get(f"/cases/{case.id}").json()["assigned_to"] is None


def test_patch_rejects_closing_and_conflicting_assignment(api, seed):
    _, case = seed("a@b", "b@b", 0.8, InterventionLevel.RESTRICT, case=(CaseStatus.OPEN, CaseSeverity.HIGH))
    assert api.patch(f"/cases/{case.id}", json={"actor": "x", "status": "closed"}).status_code == 422
    assert api.patch(f"/cases/{case.id}", json={"actor": "x", "assigned_to": "a", "unassign": True}).status_code == 422
    assert api.patch(f"/cases/{case.id}", json={"status": "investigating"}).status_code == 422  # actor required


def test_close_false_positive_does_not_mark_fraud(api, seed, db_session):
    _, case = seed("a@b", "b@b", 0.8, InterventionLevel.RESTRICT, case=(CaseStatus.OPEN, CaseSeverity.HIGH))
    resp = api.post(f"/cases/{case.id}/close", json={"actor": "ana", "resolution": "false_positive", "note": "known merchant"})
    assert resp.status_code == 200 and resp.json()["status"] == "closed"
    assert get_known_fraud_upis(db_session) == frozenset()
    closed_event = db_session.query(CaseEvent).filter_by(case_id=case.id, event_type="closed").one()
    assert closed_event.description == "false_positive: known merchant"


def test_close_fraud_confirmed_marks_receiver_as_known_fraud_once(api, seed, db_session):
    _, case = seed("a@b", "mule@b", 0.95, InterventionLevel.ESCALATE, case=(CaseStatus.ESCALATED, CaseSeverity.CRITICAL))
    api.post(f"/cases/{case.id}/confirm-fraud", json={"actor": "ana"})  # already confirmed earlier
    api.post(f"/cases/{case.id}/close", json={"actor": "ana", "resolution": "fraud_confirmed"})
    assert get_known_fraud_upis(db_session) == frozenset({"mule@b"})
    assert db_session.query(CaseEvent).filter_by(case_id=case.id, event_type="fraud_confirmed").count() == 1


def test_closed_case_is_terminal_but_still_takes_notes(api, seed):
    _, case = seed("a@b", "b@b", 0.8, InterventionLevel.RESTRICT, case=(CaseStatus.CLOSED, CaseSeverity.HIGH))
    assert api.patch(f"/cases/{case.id}", json={"actor": "x", "status": "open"}).status_code == 409
    assert api.post(f"/cases/{case.id}/close", json={"actor": "x", "resolution": "false_positive"}).status_code == 409
    assert api.post(f"/cases/{case.id}/notes", json={"actor": "x", "note": "late follow-up"}).status_code == 201


# --- overview stats ---------------------------------------------------------


def test_timeseries_is_zero_filled_and_counts_by_level(api, seed):
    seed("a@b", "b@b", 0.05, InterventionLevel.INFORM, age_h=0)
    seed("c@b", "d@b", 0.60, InterventionLevel.HOLD, age_h=0)
    seed("e@b", "f@b", 0.60, InterventionLevel.HOLD, age_h=2.5)
    seed("g@b", "h@b", 0.60, InterventionLevel.HOLD, age_h=100)  # outside the window

    buckets = api.get("/stats/timeseries?hours=6").json()
    assert len(buckets) == 6
    assert sum(b["total"] for b in buckets) == 3
    assert sum(b["counts"]["hold"] for b in buckets) == 2
    assert buckets[-1]["counts"]["inform"] == 1


def test_reason_code_counts(api, seed):
    for i in range(3):
        seed(f"a{i}@b", f"b{i}@b", 0.5, InterventionLevel.VERIFY, codes=[(ReasonCodeSource.RULE, "fan_in_velocity", 0.3)])
    seed("x@b", "y@b", 0.5, InterventionLevel.VERIFY, codes=[(ReasonCodeSource.ML, "ml_feature:amount", 0.2)])
    body = api.get("/stats/reason-codes?limit=5").json()
    assert body[0] == {"code": "fan_in_velocity", "source": "rule", "count": 3}
    assert len(body) == 2


def test_case_summary(api, seed):
    seed("a@b", "b@b", 0.9, InterventionLevel.ESCALATE, case=(CaseStatus.ESCALATED, CaseSeverity.CRITICAL))
    seed("c@b", "d@b", 0.8, InterventionLevel.RESTRICT, case=(CaseStatus.OPEN, CaseSeverity.HIGH))
    seed("e@b", "f@b", 0.8, InterventionLevel.RESTRICT, case=(CaseStatus.CLOSED, CaseSeverity.HIGH))
    body = api.get("/stats/cases").json()
    assert body["open_by_severity"] == {"low": 0, "medium": 0, "high": 1, "critical": 1}
    assert body["unassigned"] == 2 and body["closed"] == 1


# --- account profile and account-centred graph --------------------------------


def test_account_profile_aggregates(api, seed, db_session):
    seed("alice@b", "mule@b", 0.95, InterventionLevel.ESCALATE, case=(CaseStatus.ESCALATED, CaseSeverity.CRITICAL), amount="500.00")
    seed("alice@b", "shop@b", 0.05, InterventionLevel.INFORM, amount="250.00")
    seed("bob@b", "alice@b", 0.20, InterventionLevel.WARN, amount="100.00")

    body = api.get("/accounts/alice@b").json()
    assert body["transactions_sent"] == 2 and body["transactions_received"] == 1
    assert float(body["total_sent"]) == 750.0 and float(body["total_received"]) == 100.0
    assert body["counterparties"] == 3
    assert body["max_score"] == 0.95 and body["flagged_count"] == 2 and body["open_cases"] == 1
    assert body["known_fraud"] is False
    assert api.get("/accounts/ghost@b").status_code == 404


def test_account_profile_known_fraud_and_shared_device(api, seed, make_account):
    _, case = seed("a@b", "mule@b", 0.95, InterventionLevel.ESCALATE, case=(CaseStatus.ESCALATED, CaseSeverity.CRITICAL))
    api.post(f"/cases/{case.id}/confirm-fraud", json={"actor": "ana"})
    make_account("twin@b", device_id="d-mule@b")
    body = api.get("/accounts/mule@b").json()
    assert body["known_fraud"] is True
    assert body["shared_device_accounts"] == ["twin@b"]


def test_transactions_account_filter_is_exact(api, seed):
    seed("alice@b", "bob@b", 0.1, InterventionLevel.WARN)
    seed("alice2@b", "bob@b", 0.1, InterventionLevel.WARN)
    assert len(api.get("/transactions?account=alice@b").json()) == 1
    assert len(api.get("/transactions?account=bob@b").json()) == 2


def test_graph_center_limits_to_neighbourhood(api, seed):
    from app.graph.live_graph import get_transaction_graph, reset_transaction_graph
    from app.graph.schemas import GraphTransaction

    reset_transaction_graph()
    graph = get_transaction_graph()
    for i, (a, b) in enumerate([("a@b", "b@b"), ("b@b", "c@b"), ("c@b", "d@b"), ("x@b", "y@b")]):
        graph.add_transaction(
            GraphTransaction(txn_ref=f"txn:{i}", sender_upi_id=a, receiver_upi_id=b, amount=Decimal("10"), device_id=f"dev-{a}", created_at=NOW)
        )
    seed("a@b", "b@b", 0.7, InterventionLevel.HOLD)

    one_hop = api.get("/graph?center=b@b&depth=1").json()
    assert {n["id"] for n in one_hop["nodes"]} == {"a@b", "b@b", "c@b"}
    two_hop = api.get("/graph?center=b@b&depth=2").json()
    assert {n["id"] for n in two_hop["nodes"]} == {"a@b", "b@b", "c@b", "d@b"}
    assert {n["id"]: n["max_score"] for n in one_hop["nodes"]}["b@b"] == 0.7
    assert api.get("/graph?center=nobody@b").status_code == 404
    assert len(api.get("/graph?center=b@b&depth=3&max_nodes=2").json()["nodes"]) == 2
    reset_transaction_graph()


def test_ladder_matches_decision_config(api):
    from app.scoring.intervention import decide_intervention

    body = api.get("/stats/ladder").json()
    assert [e["level"] for e in body["levels"]] == ["escalate", "restrict", "hold", "verify", "warn", "inform"]
    assert sum(body["weights"].values()) == pytest.approx(1.0)
    top = body["levels"][0]
    assert decide_intervention(top["min_score"], top["min_confidence"]).value == "escalate"
