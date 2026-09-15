"""Tunable thresholds for the rules engine.

Kept as one plain dataclass (not hardcoded inside each rule function) so
the numbers can be swept during Phase 8's ablation study, or eventually
promoted to a config table/file the way Phase 6 does for the
intervention ladder, without touching rule logic.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class RuleConfig:
    # amount_above_historical_average
    min_history_for_average: int = 3
    amount_avg_multiplier: float = 3.0
    contribution_amount_avg_base: float = 0.5
    # first_time_beneficiary
    contribution_first_time_beneficiary: float = 0.15
    # fan_in_velocity
    fan_in_window_minutes: float = 10.0
    fan_in_sender_threshold: int = 5
    contribution_fan_in_base: float = 0.4
    # known_fraud_beneficiary
    contribution_known_fraud_beneficiary: float = 0.9
