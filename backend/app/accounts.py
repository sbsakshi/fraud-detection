"""Account lookup/creation -- the `upi_id` (natural key) <-> integer PK resolution
`ml/README.md` flagged as a later step, now that there's a live endpoint to do it.
"""

from __future__ import annotations

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.account import Account
from app.models.enums import AccountType


def get_account_by_upi(db: Session, upi_id: str) -> Account | None:
    return db.execute(select(Account).where(Account.upi_id == upi_id)).scalar_one_or_none()


def get_account_or_404(db: Session, upi_id: str) -> Account:
    account = get_account_by_upi(db, upi_id)
    if account is None:
        raise HTTPException(status_code=404, detail=f"No account with upi_id={upi_id!r}. Create it via POST /accounts first.")
    return account


def create_account(
    db: Session,
    upi_id: str,
    account_number: str,
    ifsc_code: str,
    owner_name: str,
    bank_name: str,
    account_type: AccountType = AccountType.INDIVIDUAL,
    device_id: str | None = None,
    true_label: str | None = None,
    is_active: bool = True,
) -> Account:
    if get_account_by_upi(db, upi_id) is not None:
        raise HTTPException(status_code=409, detail=f"Account with upi_id={upi_id!r} already exists.")
    account = Account(
        upi_id=upi_id,
        account_number=account_number,
        ifsc_code=ifsc_code,
        owner_name=owner_name,
        bank_name=bank_name,
        account_type=account_type,
        device_id=device_id,
        true_label=true_label,
        is_active=is_active,
    )
    db.add(account)
    db.commit()
    db.refresh(account)
    return account
