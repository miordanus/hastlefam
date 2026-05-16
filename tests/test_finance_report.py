"""Tests for FinanceService.monthly_report()."""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

import pytest

from app.application.services.finance_service import FinanceService
from app.domain.enums import Currency, TransactionDirection
from app.infrastructure.db.models import Account, BalanceSnapshot, Transaction
from tests.conftest import HOUSEHOLD_ID


def _make_tx(db, *, occurred_at, direction, amount, currency=Currency.RUB,
             is_planned=False, is_internal_transfer=False, primary_tag=None,
             account_id=None):
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
        is_internal_transfer=is_internal_transfer,
        is_skipped=False,
        primary_tag=primary_tag,
        extra_tags=[],
        account_id=account_id,
    )
    db.add(tx)
    return tx


def _make_account(db, name="Тест", currency=Currency.RUB):
    acc = Account(
        id=uuid.uuid4(),
        household_id=HOUSEHOLD_ID,
        name=name,
        currency=currency,
        is_shared=True,
        is_active=True,
    )
    db.add(acc)
    return acc


def _make_snapshot(db, account_id, actual_balance, created_at):
    snap = BalanceSnapshot(
        id=uuid.uuid4(),
        account_id=account_id,
        household_id=HOUSEHOLD_ID,
        actual_balance=actual_balance,
        created_at=created_at,
    )
    db.add(snap)
    return snap


def test_monthly_report_returns_accounts(seeded_db):
    acc = _make_account(seeded_db)
    seeded_db.commit()
    result = FinanceService(seeded_db).monthly_report(str(HOUSEHOLD_ID), 2026, 5)
    account_ids = [a["id"] for a in result["accounts"]]
    assert str(acc.id) in account_ids


def test_monthly_report_transactions_include_planned(seeded_db):
    acc = _make_account(seeded_db)
    seeded_db.flush()
    _make_tx(seeded_db, occurred_at=datetime(2026, 5, 10, tzinfo=timezone.utc),
             direction=TransactionDirection.EXPENSE, amount=1000, is_planned=True,
             account_id=acc.id)
    _make_tx(seeded_db, occurred_at=datetime(2026, 5, 5, tzinfo=timezone.utc),
             direction=TransactionDirection.EXPENSE, amount=500, is_planned=False,
             account_id=acc.id)
    seeded_db.commit()
    result = FinanceService(seeded_db).monthly_report(str(HOUSEHOLD_ID), 2026, 5)
    assert len(result["transactions"]) == 2


def test_monthly_report_excludes_internal_transfers(seeded_db):
    acc = _make_account(seeded_db)
    seeded_db.flush()
    _make_tx(seeded_db, occurred_at=datetime(2026, 5, 5, tzinfo=timezone.utc),
             direction=TransactionDirection.EXPENSE, amount=500,
             is_internal_transfer=True, account_id=acc.id)
    seeded_db.commit()
    result = FinanceService(seeded_db).monthly_report(str(HOUSEHOLD_ID), 2026, 5)
    assert result["transactions"] == []


def test_monthly_report_excludes_exchange_direction(seeded_db):
    acc = _make_account(seeded_db)
    seeded_db.flush()
    _make_tx(seeded_db, occurred_at=datetime(2026, 5, 5, tzinfo=timezone.utc),
             direction=TransactionDirection.EXCHANGE, amount=500, account_id=acc.id)
    seeded_db.commit()
    result = FinanceService(seeded_db).monthly_report(str(HOUSEHOLD_ID), 2026, 5)
    assert result["transactions"] == []


def test_monthly_report_excludes_other_months(seeded_db):
    acc = _make_account(seeded_db)
    seeded_db.flush()
    _make_tx(seeded_db, occurred_at=datetime(2026, 4, 30, tzinfo=timezone.utc),
             direction=TransactionDirection.EXPENSE, amount=999, account_id=acc.id)
    seeded_db.commit()
    result = FinanceService(seeded_db).monthly_report(str(HOUSEHOLD_ID), 2026, 5)
    assert result["transactions"] == []


def test_monthly_report_snapshot_latest_before_month(seeded_db):
    acc = _make_account(seeded_db)
    seeded_db.flush()
    _make_snapshot(seeded_db, acc.id, actual_balance=50000,
                   created_at=datetime(2026, 4, 28, tzinfo=timezone.utc))
    _make_snapshot(seeded_db, acc.id, actual_balance=60000,
                   created_at=datetime(2026, 5, 15, tzinfo=timezone.utc))  # inside month — excluded
    seeded_db.commit()
    result = FinanceService(seeded_db).monthly_report(str(HOUSEHOLD_ID), 2026, 5)
    snap = result["snapshots"].get(str(acc.id))
    assert snap is not None
    assert snap["actual_balance"] == 50000.0


def test_monthly_report_tag_summary_actual_expenses_only(seeded_db):
    acc = _make_account(seeded_db)
    seeded_db.flush()
    _make_tx(seeded_db, occurred_at=datetime(2026, 5, 3, tzinfo=timezone.utc),
             direction=TransactionDirection.EXPENSE, amount=5000,
             primary_tag="продукты", account_id=acc.id)
    _make_tx(seeded_db, occurred_at=datetime(2026, 5, 5, tzinfo=timezone.utc),
             direction=TransactionDirection.EXPENSE, amount=3000,
             primary_tag="продукты", is_planned=True, account_id=acc.id)  # planned — excluded from tag summary
    seeded_db.commit()
    result = FinanceService(seeded_db).monthly_report(str(HOUSEHOLD_ID), 2026, 5)
    tag = next((t for t in result["tag_summary"] if t["tag"] == "продукты"), None)
    assert tag is not None
    assert tag["total_rub"] == 5000.0  # planned not counted


# ─── Route tests ──────────────────────────────────────────────────────────────

from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app)


def test_report_data_endpoint_requires_household_id():
    resp = client.get("/finance/report/data")
    assert resp.status_code == 422  # missing required query param


def test_report_data_endpoint_returns_json(monkeypatch):
    from app.application.services.finance_service import FinanceService

    def fake_report(self, household_id, year, month):
        return {"accounts": [], "snapshots": {}, "transactions": [], "tag_summary": [],
                "year": year, "month": month}

    monkeypatch.setattr(FinanceService, "monthly_report", fake_report)
    resp = client.get("/finance/report/data?household_id=00000000-0000-0000-0000-000000000001&month=2026-05")
    assert resp.status_code == 200
    data = resp.json()
    assert "transactions" in data
    assert data["year"] == 2026
    assert data["month"] == 5
