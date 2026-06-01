"""Tests for approve & lock month (#6): snapshot totals + freeze edits."""
from __future__ import annotations

import datetime as _dt
import uuid

import pytest

from app.application.services.finance_service import FinanceService
from app.domain.enums import Currency, TransactionDirection
from app.infrastructure.db.models import Transaction
from tests.conftest import HOUSEHOLD_ID


def _tx(db, *, occurred_at, amount, direction=TransactionDirection.EXPENSE, is_planned=False):
    tx = Transaction(
        id=uuid.uuid4(), household_id=HOUSEHOLD_ID, direction=direction,
        amount=amount, currency=Currency.RUB, occurred_at=occurred_at,
        merchant_raw="x", source="test", parse_status="ok",
        is_planned=is_planned, is_internal_transfer=False, is_skipped=False,
        primary_tag="еда", extra_tags=[],
    )
    db.add(tx)
    return tx


def test_lock_snapshots_actual_totals(seeded_db):
    dt = _dt.datetime(2026, 5, 10, tzinfo=_dt.timezone.utc)
    _tx(seeded_db, occurred_at=dt, amount=1000, direction=TransactionDirection.INCOME)
    _tx(seeded_db, occurred_at=dt, amount=400, direction=TransactionDirection.EXPENSE)
    _tx(seeded_db, occurred_at=dt, amount=999, is_planned=True)  # planned → excluded
    seeded_db.commit()

    svc = FinanceService(seeded_db)
    res = svc.lock_month(str(HOUSEHOLD_ID), "2026-05")
    assert res["locked"] is True
    assert res["income_rub"] == 1000.0
    assert res["expense_rub"] == 400.0
    assert svc.is_month_locked(str(HOUSEHOLD_ID), "2026-05") is True


def test_unlock_restores(seeded_db):
    svc = FinanceService(seeded_db)
    svc.lock_month(str(HOUSEHOLD_ID), "2026-05")
    assert svc.is_month_locked(str(HOUSEHOLD_ID), "2026-05") is True
    out = svc.unlock_month(str(HOUSEHOLD_ID), "2026-05")
    assert out["locked"] is False
    assert svc.is_month_locked(str(HOUSEHOLD_ID), "2026-05") is False


def test_status_defaults_unlocked(seeded_db):
    assert FinanceService(seeded_db).month_lock_status(str(HOUSEHOLD_ID), "2026-05") == {"locked": False}


# ── Route-level enforcement. Call the route functions directly with the seeded
# session (TestClient would run them in a worker thread that can't share the
# in-memory SQLite connection). _use_rest is forced to False so the guard uses
# the SQLAlchemy path.

@pytest.fixture()
def routes(monkeypatch):
    from app.api.routers import finance as finance_router
    from app.api.schemas.finance import TransactionCreate, TransactionUpdate
    monkeypatch.setattr(finance_router, "_use_rest", lambda: False)
    return finance_router, TransactionCreate, TransactionUpdate


def _raises_423(fn):
    from fastapi import HTTPException
    with pytest.raises(HTTPException) as ei:
        fn()
    assert ei.value.status_code == 423


def test_create_blocked_in_locked_month(routes, seeded_db):
    fr, TxCreate, _ = routes
    FinanceService(seeded_db).lock_month(str(HOUSEHOLD_ID), "2026-05")
    body = TxCreate(household_id=str(HOUSEHOLD_ID), amount=100, currency="RUB",
                    direction="expense", occurred_at=_dt.date(2026, 5, 15))
    _raises_423(lambda: fr.create_transaction(body, seeded_db))


def test_create_allowed_in_open_month(routes, seeded_db):
    fr, TxCreate, _ = routes
    FinanceService(seeded_db).lock_month(str(HOUSEHOLD_ID), "2026-05")
    body = TxCreate(household_id=str(HOUSEHOLD_ID), amount=100, currency="RUB",
                    direction="expense", occurred_at=_dt.date(2026, 6, 15))
    res = fr.create_transaction(body, seeded_db)  # open month → succeeds
    assert res["ok"] is True


def test_action_blocked_in_locked_month(routes, seeded_db):
    fr, _, _ = routes
    tx = _tx(seeded_db, occurred_at=_dt.datetime(2026, 5, 9, tzinfo=_dt.timezone.utc),
             amount=50, is_planned=True)
    seeded_db.commit()
    FinanceService(seeded_db).lock_month(str(HOUSEHOLD_ID), "2026-05")
    _raises_423(lambda: fr.transaction_action(str(tx.id), "paid", seeded_db))


def test_reschedule_into_locked_month_blocked(routes, seeded_db):
    fr, _, TxUpdate = routes
    # tx lives in an open month; rescheduling it INTO a locked month must be blocked.
    tx = _tx(seeded_db, occurred_at=_dt.datetime(2026, 6, 9, tzinfo=_dt.timezone.utc),
             amount=50, is_planned=True)
    seeded_db.commit()
    FinanceService(seeded_db).lock_month(str(HOUSEHOLD_ID), "2026-05")
    _raises_423(lambda: fr.edit_transaction(str(tx.id), TxUpdate(occurred_at=_dt.date(2026, 5, 20)), seeded_db))
