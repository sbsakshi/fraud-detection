"""Tunable thresholds for the graph engine -- same rationale as `app.rules.config.RuleConfig`."""

from dataclasses import dataclass


@dataclass(frozen=True)
class GraphConfig:
    # mule_collector_pattern -- windowed: nearly every long-lived account
    # eventually accumulates fan-in >= 3 and fan-out >= 2 over its *whole*
    # history just from ordinary use, so this only means something as a
    # recent burst (see app.graph.analysis.recent_counterparties).
    collector_min_fan_in: int = 3
    # 1, not 2: this project's own mule_network scenario has each collector
    # sweep to exactly *one* cashout account (see
    # ml/synthetic/scenarios/mule_network.py) -- fan_out=1 is the real
    # signature, not "several distinct outgoing destinations."
    collector_min_fan_out: int = 1
    # Tight on purpose: the mule_network scenario compresses its whole
    # fan-in-then-sweep cycle into ~2.5 hours (see
    # ml/synthetic/scenarios/mule_network.py). A day-wide window is loose
    # enough to catch ordinary social payment splitting (three friends
    # Venmo-ing you for dinner, then paying rent yourself that evening).
    collector_window_hours: float = 3.0
    contribution_mule_collector: float = 0.6
    # shared_device_ring -- not windowed: two accounts sharing a device is a
    # persistent identity fact, not a recent-burst signal.
    shared_device_account_threshold: int = 3
    contribution_shared_device_ring: float = 0.5
    # repeated_counterparty -- windowed for the same reason as the collector
    # pattern: 5 transactions between the same pair over 2 months is an
    # ordinary recurring relationship; 5 in a day is not.
    repeated_counterparty_threshold: int = 5
    repeated_counterparty_window_hours: float = 24.0
    contribution_repeated_counterparty: float = 0.3
    # fraud_cluster_exposure
    fraud_exposure_max_hops: int = 2
    contribution_fraud_exposure_base: float = 0.7
