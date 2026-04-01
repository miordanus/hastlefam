import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from app.application.services.finance_service import FinanceService
from app.domain.enums import Currency, TransactionDirection
from app.infrastructure.db.models import PlannedPayment, Transaction
from tests.conftest import HOUSEHOLD_ID


def _add_tx(db, *, amount, direction=TransactionDirection.EXPENSE, primary_tag=None, days_ago=0):
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
        primary_tag=primary_tag,
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
    _add_tx(seeded_db, amount=100, primary_tag="groceries")
    _add_tx(seeded_db, amount=50, primary_tag="groceries")
    _add_tx(seeded_db, amount=200, direction=TransactionDirection.INCOME)

    svc = FinanceService(seeded_db)
    result = svc.month_summary(str(HOUSEHOLD_ID))
    assert result["totals"]["spend_mtd"] == Decimal("150")
    assert result["totals"]["income_mtd"] == Decimal("200")
    assert len(result["top_categories"]) == 1
    assert result["top_categories"][0]["category"] == "groceries"


def test_month_summary_uncategorized(seeded_db):
    _add_tx(seeded_db, amount=75)  # no primary_tag

    svc = FinanceService(seeded_db)
    result = svc.month_summary(str(HOUSEHOLD_ID))
    # Untagged transactions must NOT appear in top_categories/top_tags —
    # they are tracked separately in untagged_count.
    assert result["untagged_count"] == 1
    category_names = [x["category"] for x in result["top_categories"]]
    assert "без категории" not in category_names


def test_upcoming_payments(seeded_db):
    pp = PlannedPayment(
        id=uuid.uuid4(),
        household_id=HOUSEHOLD_ID,
        title="Netflix",
        amount=Decimal("15.99"),
        currency=Currency.USD,
        due_date=(datetime.now(timezone.utc) + timedelta(days=3)).date(),
        status="planned",
    )
    seeded_db.add(pp)
    seeded_db.commit()

    svc = FinanceService(seeded_db)
    items = svc.upcoming_planned(str(HOUSEHOLD_ID), days=7)
    assert len(items) == 1
    assert items[0]["title"] == "Netflix"


def test_upcoming_payments_paid_excluded(seeded_db):
    pp = PlannedPayment(
        id=uuid.uuid4(),
        household_id=HOUSEHOLD_ID,
        title="Cancelled Sub",
        amount=Decimal("9.99"),
        currency=Currency.USD,
        due_date=(datetime.now(timezone.utc) + timedelta(days=2)).date(),
        status="paid",
    )
    seeded_db.add(pp)
    seeded_db.commit()

    svc = FinanceService(seeded_db)
    items = svc.upcoming_planned(str(HOUSEHOLD_ID), days=7)
    assert len(items) == 0


def test_exchange_excluded_from_totals(seeded_db):
    _add_tx(seeded_db, amount=100, primary_tag="groceries")
    # Add exchange — should NOT appear in spend/income
    tx = Transaction(
        id=uuid.uuid4(),
        household_id=HOUSEHOLD_ID,
        direction=TransactionDirection.EXCHANGE,
        amount=Decimal("250"),
        currency=Currency.USD,
        occurred_at=datetime.now(timezone.utc),
        merchant_raw="250 USD → 230 EUR",
        source="telegram",
        parse_status="ok",
        from_amount=Decimal("250"),
        from_currency="USD",
        to_amount=Decimal("230"),
        to_currency="EUR",
        exchange_rate=Decimal("0.92"),
    )
    seeded_db.add(tx)
    seeded_db.commit()

    svc = FinanceService(seeded_db)
    result = svc.month_summary(str(HOUSEHOLD_ID))
    assert result["totals"]["spend_mtd"] == Decimal("100")  # only the groceries tx


def test_internal_transfer_excluded_from_income(seeded_db):
    _add_tx(seeded_db, amount=200, direction=TransactionDirection.INCOME)

    # Internal transfer — should NOT appear in income totals
    tx = Transaction(
        id=uuid.uuid4(),
        household_id=HOUSEHOLD_ID,
        direction=TransactionDirection.INCOME,
        amount=Decimal("90000"),
        currency=Currency.USD,
        occurred_at=datetime.now(timezone.utc),
        merchant_raw="Внесение наличных через банкомат Т-Банк",
        source="telegram",
        parse_status="ok",
        is_internal_transfer=True,
    )
    seeded_db.add(tx)
    seeded_db.commit()

    svc = FinanceService(seeded_db)
    result = svc.month_summary(str(HOUSEHOLD_ID))
    assert result["totals"]["income_mtd"] == Decimal("200")  # only real income
