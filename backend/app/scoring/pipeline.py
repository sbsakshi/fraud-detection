"""Phase 6 — the synchronous scoring path: one transaction, all three signal
sources, one fused score, one intervention decision, all in one request.

`score_and_persist_transaction` is the only function this module exposes on
purpose: everything upstream of it (rules, ML, graph) stays independently
usable and testable, and everything it does is deliberately ordered so
every signal source only ever sees state strictly before this transaction --
the rule/ML context queries run against the database *before* this
transaction is inserted, and the graph is evaluated *before*
`TransactionGraph.add_transaction` mutates it, exactly the discipline each
of those modules already documents on its own.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy.orm import Session

from app.graph import GraphContext, GraphTransaction, evaluate_graph
from app.graph.live_graph import get_transaction_graph, persist_edge_writes
from app.ml import compute_live_features, explain_ml_score, score_transaction
from app.models.account import Account
from app.models.case import Case
from app.models.case_event import CaseEvent
from app.models.enums import CaseSeverity, CaseStatus, InterventionLevel, TransactionStatus
from app.models.reason_code import ReasonCode
from app.models.risk_score import RiskScore
from app.models.transaction import Transaction
from app.rules import evaluate_rules
from app.scoring.context_builders import build_rule_context, get_known_fraud_upis
from app.scoring.fusion import fuse_scores
from app.scoring.intervention import decide_intervention

# Which intervention levels are severe enough to open an investigator case,
# and what severity/status that case starts at. ESCALATE opens the case
# already-escalated (and, via get_known_fraud_upis, feeds its receiver back
# into future scoring as a known-fraud account); RESTRICT opens it for
# review without that immediate escalation.
CASE_OPENING_LEVELS: dict[InterventionLevel, tuple[CaseStatus, CaseSeverity]] = {
    InterventionLevel.RESTRICT: (CaseStatus.OPEN, CaseSeverity.HIGH),
    InterventionLevel.ESCALATE: (CaseStatus.ESCALATED, CaseSeverity.CRITICAL),
}


@dataclass
class ScoringResult:
    transaction: Transaction
    risk_score: RiskScore
    reason_codes: list[ReasonCode]
    case: Case | None


def score_and_persist_transaction(
    db: Session,
    sender: Account,
    receiver: Account,
    amount: Decimal,
    currency: str,
    device_id: str,
    transaction_type: str,
    status: TransactionStatus = TransactionStatus.COMPLETED,
    true_label: str | None = None,
    scenario: str | None = None,
    created_at: datetime | None = None,
) -> ScoringResult:
    # Normalize to aware UTC regardless of source: defaults to now() when
    # omitted, but a client-supplied ISO timestamp with no offset parses as
    # naive, and comparing that against an aware datetime anywhere downstream
    # (rules, graph) raises rather than silently misbehaving.
    if created_at is None:
        created_at = datetime.now(timezone.utc)
    elif created_at.tzinfo is None:
        created_at = created_at.replace(tzinfo=timezone.utc)

    known_fraud_upis = get_known_fraud_upis(db)

    # --- 1. Rules (DB read-only: history strictly before this transaction) ---
    rule_ctx = build_rule_context(db, sender, receiver, amount, created_at, known_fraud_upis)
    rule_result = evaluate_rules(rule_ctx)

    # --- 2. ML (DB read-only) ---
    ml_features = compute_live_features(db, sender, receiver, amount, device_id, transaction_type, created_at)
    ml_scores = score_transaction(ml_features)
    # XGBoost and Random Forest were near-identical in Phase 4's evaluation
    # (>0.999 ROC-AUC each); averaging them is simple and doesn't lean on
    # either one's idiosyncrasies. Isolation Forest's unbounded anomaly score
    # isn't on the same probability scale, so it stays a separate reason
    # source (via explain_ml_score's SHAP contributions) rather than being
    # blended numerically into ml_score -- Phase 8's ablation is where a more
    # deliberate ensemble weighting, if warranted, should be decided.
    ml_score = (ml_scores["xgboost_score"] + ml_scores["random_forest_score"]) / 2
    ml_reasons = explain_ml_score(ml_features, top_k=3)

    # --- 3. Graph (evaluated against pre-transaction state) ---
    transaction_graph = get_transaction_graph()
    graph_txn = GraphTransaction(
        txn_ref="pending",  # evaluate_graph never reads txn_ref; the real one is assigned after the DB insert below.
        sender_upi_id=sender.upi_id,
        receiver_upi_id=receiver.upi_id,
        amount=amount,
        device_id=device_id,
        created_at=created_at,
    )
    graph_result = evaluate_graph(transaction_graph.graph, GraphContext(transaction=graph_txn, known_fraud_accounts=known_fraud_upis))

    # --- 4. Fuse + decide ---
    fusion = fuse_scores(rule_result.rule_score, ml_score, graph_result.graph_score)
    intervention_level = decide_intervention(fusion.fused_score, fusion.confidence)

    # --- 5. Persist the transaction itself ---
    transaction = Transaction(
        sender_account_id=sender.id,
        receiver_account_id=receiver.id,
        amount=amount,
        currency=currency,
        device_id=device_id,
        transaction_type=transaction_type,
        status=status,
        true_label=true_label,
        scenario=scenario,
        created_at=created_at,
    )
    db.add(transaction)
    db.flush()  # assigns transaction.id, needed below

    # --- 6. Now that it has an id, fold it into the live graph and mirror the edges ---
    edge_writes = transaction_graph.add_transaction(
        GraphTransaction(
            txn_ref=f"txn:{transaction.id}",
            sender_upi_id=sender.upi_id,
            receiver_upi_id=receiver.upi_id,
            amount=amount,
            device_id=device_id,
            created_at=created_at,
        )
    )
    persist_edge_writes(db, edge_writes, transaction.id)

    # --- 7. Persist the score + its reason codes ---
    risk_score = RiskScore(
        transaction_id=transaction.id,
        rule_score=rule_result.rule_score,
        ml_score=ml_score,
        graph_score=graph_result.graph_score,
        fused_score=fusion.fused_score,
        confidence=fusion.confidence,
        intervention_level=intervention_level,
    )
    db.add(risk_score)
    db.flush()  # assigns risk_score.id

    reason_codes = [
        ReasonCode(
            risk_score_id=risk_score.id,
            source=r.source,
            code=r.code,
            template=r.template,
            details=r.details,
            contribution=r.contribution,
        )
        for r in (*rule_result.fired, *graph_result.fired, *ml_reasons)
    ]
    db.add_all(reason_codes)

    # --- 8. Open a case for the levels severe enough to warrant one ---
    case: Case | None = None
    if intervention_level in CASE_OPENING_LEVELS:
        case_status, severity = CASE_OPENING_LEVELS[intervention_level]
        case = Case(transaction_id=transaction.id, status=case_status, severity=severity)
        db.add(case)
        db.flush()  # assigns case.id
        db.add(
            CaseEvent(
                case_id=case.id,
                event_type="case_opened",
                description=(
                    f"Opened at intervention level {intervention_level.value} "
                    f"(fused_score={fusion.fused_score:.3f}, confidence={fusion.confidence:.3f})."
                ),
                actor="system",
            )
        )

    db.commit()
    db.refresh(transaction)
    db.refresh(risk_score)
    for rc in reason_codes:
        db.refresh(rc)
    if case is not None:
        db.refresh(case)

    return ScoringResult(transaction=transaction, risk_score=risk_score, reason_codes=reason_codes, case=case)
