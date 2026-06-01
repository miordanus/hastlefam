"""Tests for the planned workbench (#2) and dual-path paid/skip action."""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

from app.application.services.finance_service import FinanceService
from app.domain.enums import Currency, TransactionDirection
from app.infrastructure.db.models import Transaction
from tests.conftest import HOUSEHOLD_ID


def _tx(db, *, occurred_at, amount, is_planned=True, is_skipped=False,
        direction=TransactionDirection.EXPENSE):
    tx = Transaction(
        id=uuid.uuid4(), household_id=HOUSEHOLD_ID, direction=direction,
        amount=amount, currency=Currency.RUB, occurred_at=occurred_at,
        merchant_raw="x", source="test", parse_status="ok",
        is_planned=is_planned, is_internal_transfer=False, is_skipped=is_skipped,
        primary_tag="еда", extra_tags=[],
    )
    db.add(tx)
    return tx


def test_planned_workbench_groups_overdue_and_upcoming(seeded_db):
    now = datetime.now(timezone.utc)
    _tx(seeded_db, occurred_at=now - timedelta(days=3), amount=100)   # overdue
    _tx(seeded_db, occurred_at=now + timedelta(days=3), amount=200)   # upcoming
    _tx(seeded_db, occurred_at=now - timedelta(days=1), amount=50, is_skipped=True)  # skipped → excluded
    _tx(seeded_db, occurred_at=now + timedelta(days=1), amount=999, is_planned=False)  # actual → excluded
    seeded_db.commit()

    wb = FinanceService(seeded_db).planned_workbench(str(HOUSEHOLD_ID))
    assert [i["amount"] for i in wb["overdue"]] == [100.0]
    assert [i["amount"] for i in wb["upcoming"]] == [200.0]
    assert wb["overdue_rub"] == 100.0
    assert wb["upcoming_rub"] == 200.0


def test_mark_transaction_paid_and_skip(seeded_db):
    now = datetime.now(timezone.utc)
    tx = _tx(seeded_db, occurred_at=now - timedelta(days=2), amount=100)
    seeded_db.commit()
    svc = FinanceService(seeded_db)

    svc.mark_transaction(str(tx.id), is_planned=False)
    seeded_db.refresh(tx)
    assert tx.is_planned is False

    svc.mark_transaction(str(tx.id), is_skipped=True)
    seeded_db.refresh(tx)
    assert tx.is_skipped is True


def test_planned_workbench_via_rest(mock_supabase):
    today = datetime.now(timezone.utc).date()
    mock_supabase.tables["accounts"] = [{"id": "acc1", "name": "Кэш"}]
    mock_supabase.tables["transactions"] = [
        {"id": "p1", "occurred_at": (today - timedelta(days=2)).isoformat(),
         "direction": "expense", "amount": 300, "currency": "rub",
         "merchant_raw": "аренда", "primary_tag": "жильё", "account_id": "acc1"},
        {"id": "p2", "occurred_at": (today + timedelta(days=10)).isoformat(),
         "direction": "income", "amount": 1000, "currency": "rub",
         "merchant_raw": "зарплата", "primary_tag": None, "account_id": "acc1"},
    ]
    mock_supabase.tables["fx_rates"] = []
    wb = FinanceService(None).planned_workbench_via_rest(str(HOUSEHOLD_ID))
    assert [i["id"] for i in wb["overdue"]] == ["p1"]
    assert [i["id"] for i in wb["upcoming"]] == ["p2"]
    assert wb["overdue"][0]["account_name"] == "Кэш"
