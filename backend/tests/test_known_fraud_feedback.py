"""Known-fraud accounts come from investigator confirmation, not from the
system's own escalations."""

from datetime import datetime, timezone
from decimal import Decimal

from fastapi.testclient import TestClient

from app.db import get_db
from app.main import app
from app.models.case import Case
from app.models.case_event import CaseEvent
from app.models.enums import CaseSeverity, CaseStatus, TransactionStatus
from app.models.transaction import Transaction
from app.scoring.context_builders import FRAUD_CONFIRMED_EVENT, get_known_fraud_upis


def _escalated_case(db_session, make_account) -> Case:
    victim = make_account("victim@bank", device_id="d1")
    mule = make_account("mule@bank", device_id="d2")
    txn = Transaction(
        sender_account_id=victim.id, receiver_account_id=mule.id, amount=Decimal("90000.00"), currency="INR",
        device_id="d9", transaction_type="P2P", status=TransactionStatus.COMPLETED,
        created_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
    )
    db_session.add(txn)
    db_session.flush()
    case = Case(transaction_id=txn.id, status=CaseStatus.ESCALATED, severity=CaseSeverity.CRITICAL)
    db_session.add(case)
    db_session.commit()
    return case


def test_escalation_alone_does_not_mark_receiver_as_known_fraud(db_session, make_account):
    _escalated_case(db_session, make_account)
    assert get_known_fraud_upis(db_session) == frozenset()


def test_confirmed_case_marks_receiver_as_known_fraud(db_session, make_account):
    case = _escalated_case(db_session, make_account)
    db_session.add(CaseEvent(case_id=case.id, event_type=FRAUD_CONFIRMED_EVENT, actor="analyst@bank"))
    db_session.commit()
    assert get_known_fraud_upis(db_session) == frozenset({"mule@bank"})


def test_confirm_fraud_endpoint_is_idempotent(db_session, make_account):
    case = _escalated_case(db_session, make_account)
    app.dependency_overrides[get_db] = lambda: db_session
    try:
        with TestClient(app) as client:
            for _ in range(2):
                resp = client.post(f"/cases/{case.id}/confirm-fraud", json={"actor": "analyst@bank", "note": "called victim"})
                assert resp.status_code == 200
                assert resp.json()["id"] == case.id
    finally:
        app.dependency_overrides.clear()
    events = db_session.query(CaseEvent).filter_by(case_id=case.id, event_type=FRAUD_CONFIRMED_EVENT).all()
    assert len(events) == 1 and events[0].actor == "analyst@bank"
    assert get_known_fraud_upis(db_session) == frozenset({"mule@bank"})
