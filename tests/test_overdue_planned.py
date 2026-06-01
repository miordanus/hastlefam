"""Tests for overdue/planned surfacing (#1) and the data-health "Сегодня" block (#7)."""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

from app.application.services.finance_service import FinanceService
from app.domain.enums import Currency, TransactionDirection
from app.infrastructure.db.models import Account, BalanceSnapshot, Transaction
from tests.conftest import HOUSEHOLD_ID


def _tx(db, *, occurred_at, amount, direction=TransactionDirection.EXPENSE,
        currency=Currency.RUB, is_planned=False, is_skipped=False, primary_tag="еда"):
    tx = Transaction(
        id=uuid.uuid4(),
        household_id=HOUSEHOLD_ID,
        direction=direction,
        amount=amount,
        currency=currency,
        occurred_at=occurred_at,
        merchant_raw="test",
        source="test",
        parse_status="ok",
        is_planned=is_planned,
        is_internal_transfer=False,
        is_skipped=is_skipped,
        primary_tag=primary_tag,
        extra_tags=[],
    )
    db.add(tx)
    return tx


def test_overdue_planned_items_surfaces_past_planned(seeded_db):
    now = datetime.now(timezone.utc)
    # Overdue planned (last month) — must surface.
    _tx(seeded_db, occurred_at=now - timedelta(days=35), amount=1000, is_planned=True)
    # Overdue planned (yesterday) — must surface.
    _tx(seeded_db, occurred_at=now - timedelta(days=1), amount=500, is_planned=True)
    # Future planned — must NOT surface (it's upcoming, not overdue).
    _tx(seeded_db, occurred_at=now + timedelta(days=5), amount=700, is_planned=True)
    # Skipped planned in the past — must NOT surface.
    _tx(seeded_db, occurred_at=now - timedelta(days=3), amount=900, is_planned=True, is_skipped=True)
    # Actual past tx — must NOT surface.
    _tx(seeded_db, occurred_at=now - timedelta(days=2), amount=100, is_planned=False)
    seeded_db.commit()

    out = FinanceService(seeded_db).overdue_planned_items(str(HOUSEHOLD_ID))
    amounts = sorted(o["amount"] for o in out)
    assert amounts == [500.0, 1000.0]
    assert all(o["amount_rub"] is not None for o in out)


def test_monthly_report_embeds_overdue_for_current_month(seeded_db):
    now = datetime.now(timezone.utc)
    _tx(seeded_db, occurred_at=now - timedelta(days=40), amount=1234, is_planned=True)
    seeded_db.commit()

    svc = FinanceService(seeded_db)
    rep = svc.monthly_report(str(HOUSEHOLD_ID), now.year, now.month)
    assert rep["is_current_month"] is True
    assert len(rep["overdue_planned"]) == 1
    assert rep["overdue_planned"][0]["amount"] == 1234.0


def test_monthly_report_no_overdue_for_past_month(seeded_db):
    now = datetime.now(timezone.utc)
    _tx(seeded_db, occurred_at=now - timedelta(days=40), amount=1234, is_planned=True)
    seeded_db.commit()

    # A clearly historical month is not "current" → no carried-in list.
    rep = FinanceService(seeded_db).monthly_report(str(HOUSEHOLD_ID), 2020, 1)
    assert rep["is_current_month"] is False
    assert rep["overdue_planned"] == []


def test_data_health_today_block(seeded_db):
    now = datetime.now(timezone.utc)
    acc = Account(id=uuid.uuid4(), household_id=HOUSEHOLD_ID, name="Кэш",
                  currency=Currency.RUB, is_shared=True, is_active=True)
    seeded_db.add(acc)
    seeded_db.flush()
    seeded_db.add(BalanceSnapshot(id=uuid.uuid4(), account_id=acc.id,
                                  household_id=HOUSEHOLD_ID, actual_balance=5000,
                                  created_at=now))
    _tx(seeded_db, occurred_at=now - timedelta(days=10), amount=300, is_planned=True)  # overdue
    _tx(seeded_db, occurred_at=now + timedelta(days=10), amount=400, is_planned=True)  # upcoming
    _tx(seeded_db, occurred_at=now - timedelta(days=1), amount=50, primary_tag=None)   # untagged
    seeded_db.commit()

    health = FinanceService(seeded_db).data_health(str(HOUSEHOLD_ID))
    t = health["today"]
    assert t["consolidated_rub"] == 5000.0
    assert t["fx_complete"] is True
    assert t["overdue_count"] == 1
    assert t["overdue_rub"] == 300.0
    assert t["upcoming_planned_count"] == 1
    assert t["untagged_count"] >= 1
    assert t["month_lock"] is None


def test_overdue_planned_items_via_rest(mock_supabase):
    today = datetime.now(timezone.utc).date()
    mock_supabase.tables["transactions"] = [
        {"id": "a", "occurred_at": (today - timedelta(days=5)).isoformat(),
         "direction": "expense", "amount": 800, "currency": "rub",
         "merchant_raw": "аренда", "primary_tag": "жильё", "account_id": None},
    ]
    mock_supabase.tables["fx_rates"] = []
    out = FinanceService(None).overdue_planned_items_via_rest(str(HOUSEHOLD_ID))
    assert len(out) == 1
    assert out[0]["amount"] == 800.0
    assert out[0]["amount_rub"] == 800.0  # rub → 1:1
