"""Tests for accounts + consolidated RUB view (#5)."""
from __future__ import annotations

import uuid
from datetime import date, datetime, timezone
from decimal import Decimal

from app.application.services.finance_service import FinanceService
from app.domain.enums import Currency
from app.infrastructure.db.models import Account, BalanceSnapshot, FxRate
from tests.conftest import HOUSEHOLD_ID


def _acc(db, name, currency):
    a = Account(id=uuid.uuid4(), household_id=HOUSEHOLD_ID, name=name,
                currency=currency, is_shared=True, is_active=True)
    db.add(a)
    db.flush()
    return a


def _snap(db, account_id, bal):
    db.add(BalanceSnapshot(id=uuid.uuid4(), account_id=account_id,
                           household_id=HOUSEHOLD_ID, actual_balance=bal,
                           created_at=datetime.now(timezone.utc)))


def test_consolidated_sums_rub_across_currencies(seeded_db):
    today = datetime.now(timezone.utc).date()
    rub_acc = _acc(seeded_db, "Тинькофф", Currency.RUB)
    usd_acc = _acc(seeded_db, "Wise", Currency.USD)
    _snap(seeded_db, rub_acc.id, 10000)
    _snap(seeded_db, usd_acc.id, 100)
    seeded_db.add(FxRate(id=uuid.uuid4(), date=today, from_currency="USD",
                         to_currency="RUB", rate=Decimal("90")))
    seeded_db.commit()

    out = FinanceService(seeded_db).list_accounts_with_balances(str(HOUSEHOLD_ID))
    assert out["fx_complete"] is True
    # 10000 RUB + 100 USD * 90 = 19000
    assert out["consolidated_rub"] == 19000.0
    usd_row = next(a for a in out["accounts"] if a["name"] == "Wise")
    assert usd_row["balance_rub"] == 9000.0


def test_missing_rate_flags_incomplete(seeded_db):
    usd_acc = _acc(seeded_db, "Wise", Currency.USD)
    _snap(seeded_db, usd_acc.id, 100)
    seeded_db.commit()  # no FxRate seeded

    out = FinanceService(seeded_db).list_accounts_with_balances(str(HOUSEHOLD_ID))
    assert out["fx_complete"] is False
    usd_row = next(a for a in out["accounts"] if a["currency"] == "USD")
    assert usd_row["balance_rub"] is None


def test_list_accounts_via_rest_consolidates(mock_supabase):
    today = date.today().isoformat()
    mock_supabase.tables["users"] = [{"id": "u1", "name": "Макс"}]
    mock_supabase.tables["accounts"] = [
        {"id": "r", "name": "Нал", "currency": "rub", "is_shared": True, "owner_user_id": None},
        {"id": "d", "name": "Wise", "currency": "usd", "is_shared": False, "owner_user_id": "u1"},
    ]
    mock_supabase.tables["balance_snapshots"] = [
        {"account_id": "r", "actual_balance": 5000, "created_at": today + "T10:00:00+00:00"},
        {"account_id": "d", "actual_balance": 50, "created_at": today + "T10:00:00+00:00"},
    ]
    mock_supabase.tables["fx_rates"] = [{"from_currency": "USD", "rate": 80, "date": today}]
    out = FinanceService(None).list_accounts_with_balances_via_rest(str(HOUSEHOLD_ID))
    # 5000 + 50*80 = 9000
    assert out["consolidated_rub"] == 9000.0
    assert out["fx_complete"] is True


def test_create_account_via_rest_posts_row(mock_supabase):
    res = FinanceService(None).create_account_via_rest(
        str(HOUSEHOLD_ID), "Новый", "USD", owner_user_id=None, is_shared=True)
    assert res["ok"] is True
    assert mock_supabase.post_calls
    table, rows = mock_supabase.post_calls[0]
    assert table == "accounts"
    assert rows[0]["currency"] == "USD"
