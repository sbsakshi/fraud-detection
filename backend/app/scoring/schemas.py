"""The one reason-code shape every signal source (rules, ML, graph) produces.

Shared so Phase 6's fusion step can treat a rule firing, an ML feature
contribution, and a graph finding identically -- each is just a
`ReasonCodeResult` with a different `source`, in the same shape the
`reason_codes` table stores (`template` with placeholders, `details` with
the filled-in values, per `app.models.reason_code.ReasonCode`).
"""

from dataclasses import dataclass

from app.models.enums import ReasonCodeSource


@dataclass(frozen=True)
class ReasonCodeResult:
    code: str
    template: str
    details: dict
    contribution: float
    source: ReasonCodeSource
