"""Shared pytest fixtures: an isolated in-memory SQLite DB per test.

SQLite stands in for Postgres here -- fine for exercising the ORM layer
(queries, joins, session lifecycle) that Phase 6's live-scoring path adds,
without needing a running Postgres for the unit test suite. Anything that
depends on a Postgres-specific feature belongs in an integration test
against the real thing instead, not here.
"""

from datetime import datetime, timezone

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.models import Account, Base
from app.models.enums import AccountType


@pytest.fixture()
def db_session():
    # StaticPool: plain sqlite:///:memory: hands a new, empty database to
    # each connection: a session that grabbed a different connection than
    # create_all did would see no tables. StaticPool keeps one connection.
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    TestingSession = sessionmaker(bind=engine)
    session = TestingSession()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


@pytest.fixture()
def make_account(db_session: Session):
    """Factory: make_account("alice@bank", device_id="d1", created_at=...) -> Account, already committed."""

    counter = iter(range(1_000_000))

    def _make(
        upi_id: str,
        device_id: str | None = None,
        account_type: AccountType = AccountType.INDIVIDUAL,
        created_at: datetime | None = None,
        true_label: str | None = None,
    ) -> Account:
        n = next(counter)
        account = Account(
            upi_id=upi_id,
            account_number=f"ACC{n:08d}",
            ifsc_code="TEST0000001",
            owner_name=f"Owner {n}",
            bank_name="Test Bank",
            account_type=account_type,
            device_id=device_id,
            true_label=true_label,
            is_active=True,
            created_at=created_at or datetime.now(timezone.utc),
        )
        db_session.add(account)
        db_session.commit()
        db_session.refresh(account)
        return account

    return _make
