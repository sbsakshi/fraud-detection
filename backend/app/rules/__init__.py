"""Phase 3 — deterministic rules engine.

Pure, DB-agnostic rule checks over a candidate transaction plus the
history needed to evaluate it. Callers (a live scoring endpoint in
Phase 6, or the synthetic-dataset evaluator here in Phase 3) build a
:class:`RuleContext` from whatever data source they have — a live
Postgres query or a CSV replay — and get back the same reason-code
shape either way.
"""

from app.rules.config import RuleConfig
from app.rules.engine import evaluate_rules
from app.rules.schemas import FiredRule, RuleContext, RuleEngineResult, RuleTransaction

__all__ = [
    "RuleConfig",
    "RuleContext",
    "RuleTransaction",
    "FiredRule",
    "RuleEngineResult",
    "evaluate_rules",
]
