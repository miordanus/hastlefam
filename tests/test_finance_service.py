import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from app.application.services.finance_service import FinanceService
from app.domain.enums import Currency, TransactionDirection
from app.infrastructure.db.models import RecurringPayment, Transaction
from tests.conftest import CATEGORY_ID, HOUSEHOLD_ID


def _add_tx(db, *, amount, direction=TransactionDirection.EXPENSE, category_id=None, days_ago=0):
    tx = Transaction(
        id=uuid.uuid4(),
        household_id=HOUSEHOLD_ID,
        direction=direction,
        amount=Decimal(str(amount)),
        currency=Currency.USD,
        occurred_at=datetime.now(timezone.utc) - timedelta(days=days_ago),
        merchant_raw="test merchant",
        source="test",
        parse_status="ok",
        parse_confidence=Decimal("0.9"),
        category_id=category_id,
    )
    db.add(tx)
    db.commit()
    return tx


def test_month_summary_empty(seeded_db):
    svc = FinanceService(seeded_db)
    result = svc.month_summary(str(HOUSEHOLD_ID))
    assert result["totals"]["spend_mtd"] == Decimal("0")
    assert result["totals"]["income_mtd"] == Decimal("0")


def test_month_summary_with_expenses(seeded_db):
    _add_tx(seeded_db, amount=100, category_id=CATEGORY_ID)
    _add_tx(seeded_db, amount=50, category_id=CATEGORY_ID)
    _add_tx(seeded_db, amount=200, direction=TransactionDirection.INCOME)

    svc = FinanceService(seeded_db)
    result = svc.month_summary(str(HOUSEHOLD_ID))
    assert result["totals"]["spend_mtd"] == Decimal("150")
    assert result["totals"]["income_mtd"] == Decimal("200")
    assert len(result["top_categories"]) == 1
    assert result["top_categories"][0]["category"] == "Groceries"


def test_month_summary_uncategorized(seeded_db):
    _add_tx(seeded_db, amount=75)  # no category

    svc = FinanceService(seeded_db)
    result = svc.month_summary(str(HOUSEHOLD_ID))
    assert result["top_categories"][0]["category"] == "Uncategorized"


def test_upcoming_payments(seeded_db):
    rec = RecurringPayment(
        id=uuid.uuid4(),
        household_id=HOUSEHOLD_ID,
        title="Netflix",
        amount_expected=Decimal("15.99"),
        currency=Currency.USD,
        cadence="monthly",
        next_due_date=(datetime.now(timezone.utc) + timedelta(days=3)).date(),
        is_active=True,
    )
    seeded_db.add(rec)
    seeded_db.commit()

    svc = FinanceService(seeded_db)
    items = svc.upcoming_payments(str(HOUSEHOLD_ID), days=7)
    assert len(items) == 1
    assert items[0]["title"] == "Netflix"


def test_upcoming_payments_inactive_excluded(seeded_db):
    rec = RecurringPayment(
        id=uuid.uuid4(),
        household_id=HOUSEHOLD_ID,
        title="Cancelled Sub",
        amount_expected=Decimal("9.99"),
        currency=Currency.USD,
        cadence="monthly",
        next_due_date=(datetime.now(timezone.utc) + timedelta(days=2)).date(),
        is_active=False,
    )
    seeded_db.add(rec)
    seeded_db.commit()

    svc = FinanceService(seeded_db)
    items = svc.upcoming_payments(str(HOUSEHOLD_ID), days=7)
    assert len(items) == 0
