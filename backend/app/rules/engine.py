"""The four Phase 3 rules and the orchestrator that runs them.

Each `rule_*` function takes a `RuleContext` (+ `RuleConfig`) and returns
either a `FiredRule` — a reason code, not a bare boolean — or `None` if
the rule didn't fire. `evaluate_rules` runs the full set and fuses the
individual contributions into one `rule_score`, later combined with the
ML and graph scores in Phase 6.
"""

from datetime import timedelta
from statistics import mean

from app.rules.config import RuleConfig
from app.rules.schemas import FiredRule, RuleContext, RuleEngineResult


def rule_known_fraud_beneficiary(ctx: RuleContext, config: RuleConfig) -> FiredRule | None:
    """Receiver appears on the known-fraud beneficiary watchlist.

    The watchlist itself is just a set of UPI ids injected via the
    context — where it comes from (e.g. accounts tied to escalated
    cases) is a Phase 6 concern, not this rule's.
    """
    receiver = ctx.transaction.receiver_upi_id
    if receiver not in ctx.known_fraud_beneficiaries:
        return None
    return FiredRule(
        code="known_fraud_beneficiary",
        template="Receiver {receiver_upi_id} is on the known-fraud beneficiary watchlist.",
        details={"receiver_upi_id": receiver},
        contribution=config.contribution_known_fraud_beneficiary,
    )


def rule_amount_above_historical_average(ctx: RuleContext, config: RuleConfig) -> FiredRule | None:
    """Amount is well above the sender's own historical average.

    Needs at least `min_history_for_average` prior transactions to trust
    an average at all — a sender's first couple of transfers don't have
    a meaningful baseline yet, so this rule stays silent for them
    (the fresh-account case is covered by `rule_first_time_beneficiary`
    and, later, an account-age signal in Phase 4/5 instead).
    """
    history = ctx.sender_prior_transactions
    if len(history) < config.min_history_for_average:
        return None
    avg = mean(float(t.amount) for t in history)
    if avg <= 0:
        return None
    ratio = float(ctx.transaction.amount) / avg
    if ratio < config.amount_avg_multiplier:
        return None
    contribution = min(1.0, config.contribution_amount_avg_base * (ratio / config.amount_avg_multiplier))
    return FiredRule(
        code="amount_above_historical_average",
        template="Amount {amount:.2f} is {ratio:.1f}x the account's historical average of {avg:.2f}.",
        details={"amount": float(ctx.transaction.amount), "ratio": round(ratio, 1), "avg": round(avg, 2)},
        contribution=contribution,
    )


def rule_first_time_beneficiary(ctx: RuleContext, config: RuleConfig) -> FiredRule | None:
    """Sender has never sent to this receiver before.

    Common on its own (most legitimate transactions have a first time
    too), so it carries a small contribution — signal that only really
    matters stacked with another rule firing on the same transaction.
    """
    receiver = ctx.transaction.receiver_upi_id
    if any(t.receiver_upi_id == receiver for t in ctx.sender_prior_transactions):
        return None
    return FiredRule(
        code="first_time_beneficiary",
        template="First transaction between {sender_upi_id} and {receiver_upi_id}.",
        details={"sender_upi_id": ctx.transaction.sender_upi_id, "receiver_upi_id": receiver},
        contribution=config.contribution_first_time_beneficiary,
    )


def rule_fan_in_velocity(ctx: RuleContext, config: RuleConfig) -> FiredRule | None:
    """Unusually many distinct senders paying one receiver in a short window."""
    window = timedelta(minutes=config.fan_in_window_minutes)
    cutoff = ctx.transaction.created_at - window
    senders_in_window = {
        sender
        for sender, sent_at in ctx.receiver_prior_senders
        if cutoff <= sent_at <= ctx.transaction.created_at
    }
    senders_in_window.add(ctx.transaction.sender_upi_id)
    count = len(senders_in_window)
    if count < config.fan_in_sender_threshold:
        return None
    contribution = min(1.0, config.contribution_fan_in_base * (count / config.fan_in_sender_threshold))
    return FiredRule(
        code="fan_in_velocity",
        template=(
            "{count} distinct senders paid {receiver_upi_id} within the last {window_minutes:.0f} minutes."
        ),
        details={
            "count": count,
            "receiver_upi_id": ctx.transaction.receiver_upi_id,
            "window_minutes": config.fan_in_window_minutes,
        },
        contribution=contribution,
    )


ALL_RULES = (
    rule_known_fraud_beneficiary,
    rule_amount_above_historical_average,
    rule_first_time_beneficiary,
    rule_fan_in_velocity,
)


def evaluate_rules(ctx: RuleContext, config: RuleConfig | None = None) -> RuleEngineResult:
    """Run every rule against `ctx` and fuse the results into one score.

    `rule_score` is an additive, capped-at-1.0 combination of whichever
    rules fired — simple on purpose; Phase 6 is where rule/ML/graph
    scores get fused with confidence, not this function.
    """
    config = config or RuleConfig()
    fired = tuple(result for rule in ALL_RULES if (result := rule(ctx, config)) is not None)
    rule_score = min(1.0, sum(r.contribution for r in fired)) if fired else 0.0
    return RuleEngineResult(fired=fired, rule_score=rule_score)
