from datetime import datetime, timezone
from decimal import Decimal
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, Enum, ForeignKey, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base
from app.models.enums import TransactionStatus

if TYPE_CHECKING:
    from app.models.account import Account


class Transaction(Base):
    __tablename__ = "transactions"

    id: Mapped[int] = mapped_column(primary_key=True)
    sender_account_id: Mapped[int] = mapped_column(
        ForeignKey("accounts.id"), nullable=False, index=True
    )
    receiver_account_id: Mapped[int] = mapped_column(
        ForeignKey("accounts.id"), nullable=False, index=True
    )
    amount: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False, default="INR")
    device_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    transaction_type: Mapped[str] = mapped_column(String(16), nullable=False, default="P2P")
    status: Mapped[TransactionStatus] = mapped_column(
        Enum(TransactionStatus, name="transaction_status"),
        nullable=False,
        default=TransactionStatus.COMPLETED,
    )
    # Ground-truth fraud label and originating scenario injector, for the synthetic dataset.
    true_label: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    scenario: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc), index=True
    )

    sender: Mapped["Account"] = relationship(foreign_keys=[sender_account_id])
    receiver: Mapped["Account"] = relationship(foreign_keys=[receiver_account_id])
