from datetime import datetime, timedelta, timezone
from decimal import Decimal

from app.ml.feature_engineering import NO_HISTORY
from app.ml.live_features import compute_live_features
from app.models.enums import TransactionStatus
from app.models.transaction import Transaction

NOW = datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)


def add_transaction(db_session, sender, receiver, amount, minutes_before_now, device_id="d1"):
    t = Transaction(
        sender_account_id=sender.id,
        receiver_account_id=receiver.id,
        amount=Decimal(amount),
        currency="INR",
        device_id=device_id,
        transaction_type="P2P",
        status=TransactionStatus.COMPLETED,
        created_at=NOW - timedelta(minutes=minutes_before_now),
    )
    db_session.add(t)
    db_session.commit()
    return t


def test_first_transaction_has_no_history_sentinels(db_session, make_account):
    alice = make_account("alice@bank", device_id="d1", created_at=NOW - timedelta(days=30))
    bob = make_account("bob@bank", device_id="d2", created_at=NOW - timedelta(days=30))

    features = compute_live_features(
        db_session, alice, bob, amount=Decimal("100.00"), device_id="d1",
        transaction_type="P2P", created_at=NOW,
    )
    assert features["sender_txn_count_hist"] == 0
    assert features["is_first_time_beneficiary"] == 1
    assert features["amount_zscore_sender"] == NO_HISTORY
    assert features["is_new_device_for_sender"] == 1
    assert 29.9 < features["sender_account_age_days"] < 30.1


def test_reflects_prior_history_between_the_same_pair(db_session, make_account):
    alice = make_account("alice@bank", device_id="d1", created_at=NOW - timedelta(days=60))
    bob = make_account("bob@bank", device_id="d2", created_at=NOW - timedelta(days=60))
    for i in range(3):
        add_transaction(db_session, alice, bob, "100.00", minutes_before_now=(3 - i) * 60)

    features = compute_live_features(
        db_session, alice, bob, amount=Decimal("110.00"), device_id="d1",
        transaction_type="P2P", created_at=NOW,
    )
    assert features["sender_txn_count_hist"] == 3
    assert features["is_first_time_beneficiary"] == 0
    assert features["sender_amount_mean_hist"] == 100.0


def test_amount_far_above_average_shows_high_zscore(db_session, make_account):
    alice = make_account("alice@bank", device_id="d1", created_at=NOW - timedelta(days=60))
    bob = make_account("bob@bank", device_id="d2", created_at=NOW - timedelta(days=60))
    carol = make_account("carol@bank", device_id="d3", created_at=NOW - timedelta(days=60))
    for i, amount in enumerate(["95.00", "100.00", "105.00", "98.00", "102.00"]):
        add_transaction(db_session, alice, bob, amount, minutes_before_now=(5 - i) * 60)

    features = compute_live_features(
        db_session, alice, carol, amount=Decimal("5000.00"), device_id="d1",
        transaction_type="P2P", created_at=NOW,
    )
    assert features["amount_to_sender_avg_ratio"] > 40
    assert features["amount_zscore_sender"] > 0
    assert features["is_first_time_beneficiary"] == 1  # alice has never paid carol before


def test_only_pulls_history_strictly_before_the_candidate(db_session, make_account):
    alice = make_account("alice@bank", device_id="d1", created_at=NOW - timedelta(days=60))
    bob = make_account("bob@bank", device_id="d2", created_at=NOW - timedelta(days=60))
    # A transaction *after* the candidate's timestamp must not leak into its features.
    add_transaction(db_session, alice, bob, "100.00", minutes_before_now=-60)

    features = compute_live_features(
        db_session, alice, bob, amount=Decimal("100.00"), device_id="d1",
        transaction_type="P2P", created_at=NOW,
    )
    assert features["sender_txn_count_hist"] == 0
    assert features["is_first_time_beneficiary"] == 1
