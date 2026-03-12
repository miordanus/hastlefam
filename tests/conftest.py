import os
import uuid
from datetime import datetime, timezone

# Set dummy env vars before any app imports trigger Settings()
os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")
os.environ.setdefault("ALEMBIC_DATABASE_URL", "sqlite:///:memory:")
os.environ.setdefault("TELEGRAM_BOT_TOKEN", "test-token")
os.environ.setdefault("OPENAI_API_KEY", "test-key")

import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker

from app.infrastructure.db.base import Base
from app.infrastructure.db.models import (
    Account,
    FinanceCategory,
    Household,
    Owner,
    RecurringPayment,
    Transaction,
    User,
)
from app.domain.enums import CategoryKind, Currency, TransactionDirection


@pytest.fixture()
def db():
    engine = create_engine("sqlite:///:memory:")

    # SQLite doesn't support schemas — remove schema from metadata for tests
    for table in Base.metadata.tables.values():
        table.schema = None

    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    try:
        yield session
    finally:
        session.close()
        Base.metadata.drop_all(engine)
        # Restore schema for other test isolation
        for table in Base.metadata.tables.values():
            table.schema = "hastlefam"


HOUSEHOLD_ID = uuid.uuid4()
USER_ID = uuid.uuid4()
OWNER_ID = uuid.uuid4()
ACCOUNT_ID = uuid.uuid4()
CATEGORY_ID = uuid.uuid4()


@pytest.fixture()
def seeded_db(db):
    household = Household(id=HOUSEHOLD_ID, name="Test Family")
    db.add(household)

    user = User(
        id=USER_ID,
        household_id=HOUSEHOLD_ID,
        telegram_id="123456",
        name="Test User",
    )
    db.add(user)

    owner = Owner(
        id=OWNER_ID,
        household_id=HOUSEHOLD_ID,
        name="Test Owner",
        slug="test",
    )
    db.add(owner)

    account = Account(
        id=ACCOUNT_ID,
        household_id=HOUSEHOLD_ID,
        name="Main Account",
        currency=Currency.USD,
    )
    db.add(account)

    category = FinanceCategory(
        id=CATEGORY_ID,
        household_id=HOUSEHOLD_ID,
        name="Groceries",
        kind=CategoryKind.EXPENSE,
    )
    db.add(category)

    db.commit()
    return db
