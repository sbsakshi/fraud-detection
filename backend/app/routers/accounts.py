"""Account provisioning -- create the accounts a transaction can then reference.

Phase 7's replay script seeds every synthetic account through this
(from `ml/data/accounts.csv`) before replaying `ml/data/transactions.csv`
through `POST /transactions`; `POST /transactions` itself never creates an
account implicitly (see `app.accounts.get_account_or_404`) so a typo'd
`upi_id` fails loudly instead of silently fabricating an account.
"""

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.accounts import create_account
from app.db import get_db
from app.schemas import AccountCreate, AccountOut

router = APIRouter(prefix="/accounts", tags=["accounts"])


@router.post("", response_model=AccountOut, status_code=201)
def create_account_endpoint(payload: AccountCreate, db: Session = Depends(get_db)) -> AccountOut:
    account = create_account(
        db,
        upi_id=payload.upi_id,
        account_number=payload.account_number,
        ifsc_code=payload.ifsc_code,
        owner_name=payload.owner_name,
        bank_name=payload.bank_name,
        account_type=payload.account_type,
        device_id=payload.device_id,
        true_label=payload.true_label,
        is_active=payload.is_active,
    )
    return AccountOut.model_validate(account)
