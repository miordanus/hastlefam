import uuid
from datetime import date, timedelta, datetime, timezone

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import os
os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")
os.environ.setdefault("ALEMBIC_DATABASE_URL", "sqlite:///:memory:")
os.environ.setdefault("TELEGRAM_BOT_TOKEN", "test-token")
os.environ.setdefault("OPENAI_API_KEY", "test-key")
os.environ.setdefault("SUPABASE_URL", "http://stub.local")
os.environ.setdefault("SUPABASE_SERVICE_ROLE_KEY", "stub-key")

from app.application.services.finance_service import FinanceService
from app.domain.enums import Currency, TransactionDirection
from app.infrastructure.db.base import Base
from app.infrastructure.db.models import Household, Transaction, User


HID = uuid.uuid4()


@pytest.fixture()
def db():
    engine = create_engine("sqlite:///:memory:")
    for t in Base.metadata.tables.values():
        t.schema = None
    Base.metadata.create_all(engine)
    S = sessionmaker(bind=engine)
    session = S()
    hh = Household(id=HID, name="Test")
    session.add(hh)
    session.commit()
    try:
        yield session
    finally:
        session.close()
        Base.metadata.drop_all(engine)
        for t in Base.metadata.tables.values():
            t.schema = "hastlefam"


def _planned_tx(db, days_from_now: int, amount=1000, direction=TransactionDirection.EXPENSE):
    today = datetime.now(timezone.utc).date()
    due = today + timedelta(days=days_from_now)
    tx = Transaction(
        id=uuid.uuid4(),
        household_id=HID,
        amount=amount,
        currency=Currency.RUB,
        direction=direction,
        occurred_at=datetime(due.year, due.month, due.day, 12, 0, tzinfo=timezone.utc),
        is_planned=True,
        is_skipped=False,
        dedup_fingerprint=str(uuid.uuid4()),
    )
    db.add(tx)
    db.commit()
    return tx


def test_forecast_empty(db):
    result = FinanceService(db).forecast_by_week(str(HID))
    assert result["weeks"] == []
    assert result["overdue"] == []


def test_forecast_groups_by_week(db):
    _planned_tx(db, days_from_now=3, amount=1000)   # this week or next
    _planned_tx(db, days_from_now=10, amount=2000)  # different week
    result = FinanceService(db).forecast_by_week(str(HID))
    assert len(result["weeks"]) == 2
    total_amounts = sum(w["total_expense"] for w in result["weeks"])
    assert total_amounts == 3000


def test_forecast_excludes_beyond_42_days(db):
    _planned_tx(db, days_from_now=50)  # beyond 6 weeks
    result = FinanceService(db).forecast_by_week(str(HID))
    assert result["weeks"] == []


def test_forecast_week_label_same_month():
    from app.application.services.finance_service import _forecast_week_label
    assert _forecast_week_label(date(2026, 6, 15), date(2026, 6, 21)) == "15–21 июн"


def test_forecast_week_label_cross_month():
    from app.application.services.finance_service import _forecast_week_label
    assert _forecast_week_label(date(2026, 6, 29), date(2026, 7, 5)) == "29 июн–5 июл"
