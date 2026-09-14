from datetime import datetime, timezone

from sqlalchemy import JSON, DateTime, Enum, Float, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base
from app.models.enums import ReasonCodeSource


class ReasonCode(Base):
    __tablename__ = "reason_codes"

    id: Mapped[int] = mapped_column(primary_key=True)
    risk_score_id: Mapped[int] = mapped_column(
        ForeignKey("risk_scores.id"), nullable=False, index=True
    )
    source: Mapped[ReasonCodeSource] = mapped_column(
        Enum(ReasonCodeSource, name="reason_code_source"), nullable=False
    )
    code: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    # Human-readable template with placeholders, e.g. "Amount ₹{amount} is {ratio}x the account's historical average"
    template: Mapped[str] = mapped_column(String(512), nullable=False)
    # Filled-in template values, e.g. {"amount": 50000, "ratio": 8.2}
    details: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    contribution: Mapped[float | None] = mapped_column(Float, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc)
    )
