from datetime import datetime, timedelta
from decimal import Decimal

import pytest

from app.rules import RuleConfig, RuleContext, RuleTransaction, evaluate_rules
from app.rules.engine import (
    rule_amount_above_historical_average,
    rule_fan_in_velocity,
    rule_first_time_beneficiary,
    rule_known_fraud_beneficiary,
)

NOW = datetime(2026, 1, 1, 12, 0, 0)


def txn(sender: str, receiver: str, amount: str, minutes_before_now: float) -> RuleTransaction:
    return RuleTransaction(
        sender_upi_id=sender,
        receiver_upi_id=receiver,
        amount=Decimal(amount),
        created_at=NOW - timedelta(minutes=minutes_before_now),
    )


def candidate(sender="alice@bank", receiver="bob@bank", amount="1000.00") -> RuleTransaction:
    return RuleTransaction(sender_upi_id=sender, receiver_upi_id=receiver, amount=Decimal(amount), created_at=NOW)


class TestKnownFraudBeneficiary:
    def test_fires_when_receiver_on_watchlist(self):
        ctx = RuleContext(transaction=candidate(receiver="mule@bank"), known_fraud_beneficiaries=frozenset({"mule@bank"}))
        fired = rule_known_fraud_beneficiary(ctx, RuleConfig())
        assert fired is not None
        assert fired.code == "known_fraud_beneficiary"
        assert fired.details["receiver_upi_id"] == "mule@bank"

    def test_silent_when_receiver_not_on_watchlist(self):
        ctx = RuleContext(transaction=candidate(), known_fraud_beneficiaries=frozenset({"someone_else@bank"}))
        assert rule_known_fraud_beneficiary(ctx, RuleConfig()) is None


class TestAmountAboveHistoricalAverage:
    def test_silent_with_insufficient_history(self):
        history = [txn("alice@bank", "x@bank", "100.00", 60), txn("alice@bank", "y@bank", "100.00", 30)]
        ctx = RuleContext(transaction=candidate(amount="10000.00"), sender_prior_transactions=history)
        assert rule_amount_above_historical_average(ctx, RuleConfig()) is None

    def test_silent_when_amount_close_to_average(self):
        history = [txn("alice@bank", "x@bank", "100.00", m) for m in (60, 45, 30)]
        ctx = RuleContext(transaction=candidate(amount="120.00"), sender_prior_transactions=history)
        assert rule_amount_above_historical_average(ctx, RuleConfig()) is None

    def test_fires_when_amount_well_above_average(self):
        history = [txn("alice@bank", "x@bank", "100.00", m) for m in (60, 45, 30)]
        ctx = RuleContext(transaction=candidate(amount="1000.00"), sender_prior_transactions=history)
        fired = rule_amount_above_historical_average(ctx, RuleConfig())
        assert fired is not None
        assert fired.details["ratio"] == pytest.approx(10.0)
        assert 0 < fired.contribution <= 1.0


class TestFirstTimeBeneficiary:
    def test_fires_when_no_prior_transaction_to_receiver(self):
        history = [txn("alice@bank", "someone_else@bank", "50.00", 60)]
        ctx = RuleContext(transaction=candidate(receiver="bob@bank"), sender_prior_transactions=history)
        fired = rule_first_time_beneficiary(ctx, RuleConfig())
        assert fired is not None
        assert fired.code == "first_time_beneficiary"

    def test_silent_when_receiver_seen_before(self):
        history = [txn("alice@bank", "bob@bank", "50.00", 60)]
        ctx = RuleContext(transaction=candidate(receiver="bob@bank"), sender_prior_transactions=history)
        assert rule_first_time_beneficiary(ctx, RuleConfig()) is None


class TestFanInVelocity:
    def test_fires_when_many_distinct_senders_in_window(self):
        prior_senders = [(f"sender{i}@bank", NOW - timedelta(minutes=m)) for i, m in enumerate([1, 2, 3, 4])]
        ctx = RuleContext(
            transaction=candidate(sender="sender5@bank", receiver="collector@bank"),
            receiver_prior_senders=prior_senders,
        )
        fired = rule_fan_in_velocity(ctx, RuleConfig())
        assert fired is not None
        assert fired.details["count"] == 5

    def test_silent_when_below_threshold(self):
        prior_senders = [(f"sender{i}@bank", NOW - timedelta(minutes=m)) for i, m in enumerate([1, 2])]
        ctx = RuleContext(
            transaction=candidate(sender="sender3@bank", receiver="collector@bank"),
            receiver_prior_senders=prior_senders,
        )
        assert rule_fan_in_velocity(ctx, RuleConfig()) is None

    def test_ignores_senders_outside_window(self):
        prior_senders = [(f"sender{i}@bank", NOW - timedelta(minutes=60)) for i in range(4)]
        ctx = RuleContext(
            transaction=candidate(sender="sender5@bank", receiver="collector@bank"),
            receiver_prior_senders=prior_senders,
        )
        assert rule_fan_in_velocity(ctx, RuleConfig()) is None

    def test_repeated_sender_only_counted_once(self):
        prior_senders = [("dup@bank", NOW - timedelta(minutes=m)) for m in (1, 2, 3, 4)]
        ctx = RuleContext(
            transaction=candidate(sender="dup@bank", receiver="collector@bank"),
            receiver_prior_senders=prior_senders,
        )
        assert rule_fan_in_velocity(ctx, RuleConfig()) is None


class TestEvaluateRules:
    def test_no_rules_fire_on_ordinary_repeat_transaction(self):
        history = [txn("alice@bank", "bob@bank", "100.00", m) for m in (60, 45, 30)]
        ctx = RuleContext(transaction=candidate(amount="110.00"), sender_prior_transactions=history)
        result = evaluate_rules(ctx)
        assert result.fired == ()
        assert result.rule_score == 0.0

    def test_score_is_additive_and_capped_at_one(self):
        # Stack known-fraud-beneficiary (0.9) with first-time-beneficiary (0.15) -> would be 1.05 uncapped.
        ctx = RuleContext(
            transaction=candidate(receiver="mule@bank"),
            known_fraud_beneficiaries=frozenset({"mule@bank"}),
        )
        result = evaluate_rules(ctx)
        codes = {r.code for r in result.fired}
        assert codes == {"known_fraud_beneficiary", "first_time_beneficiary"}
        assert result.rule_score == 1.0

    def test_innocent_bystander_style_transaction_stays_clean(self):
        # A perfectly ordinary transaction between two established accounts
        # should not trip any rule -- guards against false positives.
        history = [txn("alice@bank", "bob@bank", "500.00", m) for m in (600, 500, 400, 300)]
        ctx = RuleContext(transaction=candidate(amount="520.00"), sender_prior_transactions=history)
        result = evaluate_rules(ctx)
        assert result.fired == ()
