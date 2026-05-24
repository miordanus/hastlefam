import os
import uuid
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

# Set dummy env vars before any app imports trigger Settings()
os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")
os.environ.setdefault("ALEMBIC_DATABASE_URL", "sqlite:///:memory:")
os.environ.setdefault("TELEGRAM_BOT_TOKEN", "test-token")
os.environ.setdefault("OPENAI_API_KEY", "test-key")
os.environ.setdefault("SUPABASE_URL", "http://stub.local")
os.environ.setdefault("SUPABASE_SERVICE_ROLE_KEY", "stub-key")

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


# ─── SupabaseClient mock for *_via_rest service methods ──────────────────────
# Tests preload `mock_supabase.tables[<table>] = [row, ...]` and the patched
# client's `.get(table, params)` returns those rows. PostgREST-style filters
# in `params` are NOT applied (tests should preload only the rows they want
# returned for a given query) — keep fixtures small and explicit.

class _StubSupabase:
    def __init__(self):
        self.tables: dict[str, list[dict]] = {}
        self.get_calls: list[tuple[str, dict]] = []

    def get(self, table, params=None):
        self.get_calls.append((table, dict(params or {})))
        return list(self.tables.get(table, []))

    def rpc(self, name, params=None):
        # Not used by the methods under test, but stub it just in case.
        return list(self.tables.get(f"rpc:{name}", []))

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


@pytest.fixture()
def mock_supabase():
    """Patch SupabaseClient where *_via_rest methods import it from."""
    stub = _StubSupabase()
    # The service methods do `from app.infrastructure.supabase import SupabaseClient`
    # inside the function body, so we patch the module attribute used at call time.
    with patch("app.infrastructure.supabase.SupabaseClient", return_value=stub):
        yield stub
