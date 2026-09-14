from datetime import datetime, timezone

from sqlalchemy import Boolean, DateTime, Enum, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base
from app.models.enums import AccountType


class Account(Base):
    __tablename__ = "accounts"

    id: Mapped[int] = mapped_column(primary_key=True)
    upi_id: Mapped[str] = mapped_column(String(64), unique=True, index=True, nullable=False)
    account_number: Mapped[str] = mapped_column(String(32), nullable=False)
    ifsc_code: Mapped[str] = mapped_column(String(16), nullable=False)
    owner_name: Mapped[str] = mapped_column(String(128), nullable=False)
    bank_name: Mapped[str] = mapped_column(String(128), nullable=False)
    account_type: Mapped[AccountType] = mapped_column(
        Enum(AccountType, name="account_type"), nullable=False, default=AccountType.INDIVIDUAL
    )
    device_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    # Ground-truth label for synthetic data (e.g. "mule", "scam_recipient"); null for normal accounts.
    true_label: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc)
    )
