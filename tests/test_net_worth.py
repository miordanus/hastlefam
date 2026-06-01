"""Tests for FinanceService.net_worth_rub (Task 3).

Net worth values each account's latest snapshot in RUB using the *real* applied
exchange rate (valuation_rate_to_rub), falling back to CBR, and flags when a
currency has no rate at all.
"""
from __future__ import annotations

import uuid
from datetime import date, datetime, timezone
from decimal import Decimal

from app.application.services.finance_service import FinanceService
from app.domain.enums import Currency, TransactionDirection
from app.infrastructure.db.models import Account, BalanceSnapshot, FxRate, Transaction
from tests.conftest import HOUSEHOLD_ID


def _account(db, name, currency):
    acc = Account(id=uuid.uuid4(), household_id=HOUSEHOLD_ID, name=name,
                  currency=currency, is_shared=True, is_active=True)
    db.add(acc)
    return acc


def _snapshot(db, account_id, amount, when=datetime(2026, 5, 20, tzinfo=timezone.utc)):
    db.add(BalanceSnapshot(id=uuid.uuid4(), account_id=account_id, household_id=HOUSEHOLD_ID,
                           actual_balance=Decimal(str(amount)), created_at=when))


def _exchange(db, *, from_amount, from_cur, to_amount, to_cur):
    db.add(Transaction(
        id=uuid.uuid4(), household_id=HOUSEHOLD_ID, direction=TransactionDirection.EXCHANGE,
        amount=Decimal(str(from_amount)), currency=Currency.RUB,
        occurred_at=datetime(2026, 5, 10, tzinfo=timezone.utc), merchant_raw="x", source="test",
        parse_status="ok", from_amount=Decimal(str(from_amount)), from_currency=from_cur,
        to_amount=Decimal(str(to_amount)), to_currency=to_cur,
        exchange_rate=Decimal(str(to_amount)) / Decimal(str(from_amount)), extra_tags=[],
        is_planned=False, is_internal_transfer=False, is_skipped=False))


def test_net_worth_values_usd_at_actual_rate(seeded_db):
    usd = _account(seeded_db, "Crypto", Currency.USD)
    _snapshot(seeded_db, usd.id, 100)
    _exchange(seeded_db, from_amount=10000, from_cur="RUB", to_amount=100, to_cur="USD")  # 100 RUB/USD
    seeded_db.commit()
    out = FinanceService(seeded_db).net_worth_rub(str(HOUSEHOLD_ID))
    assert out["total_rub"] == Decimal("10000")
    assert out["any_unavailable"] is False
    card = next(a for a in out["accounts"] if a["currency"] == "USD")
    assert card["rate_source"] == "actual"


def test_net_worth_sums_multiple_accounts(seeded_db):
    usd = _account(seeded_db, "Crypto", Currency.USD)
    rub = _account(seeded_db, "Нал", Currency.RUB)
    _snapshot(seeded_db, usd.id, 100)
    _snapshot(seeded_db, rub.id, 5000)
    _exchange(seeded_db, from_amount=10000, from_cur="RUB", to_amount=100, to_cur="USD")
    seeded_db.commit()
    out = FinanceService(seeded_db).net_worth_rub(str(HOUSEHOLD_ID))
    assert out["total_rub"] == Decimal("15000")  # 100×100 + 5000


def test_net_worth_falls_back_to_cbr(seeded_db):
    usd = _account(seeded_db, "Crypto", Currency.USD)
    _snapshot(seeded_db, usd.id, 100)
    seeded_db.add(FxRate(id=uuid.uuid4(), date=date(2026, 5, 20), from_currency="USD",
                         to_currency="RUB", rate=Decimal("70")))
    seeded_db.commit()
    out = FinanceService(seeded_db).net_worth_rub(str(HOUSEHOLD_ID), for_date=date(2026, 5, 20))
    assert out["total_rub"] == Decimal("7000")
    card = next(a for a in out["accounts"] if a["currency"] == "USD")
    assert card["rate_source"] == "cbr"


def test_net_worth_flags_unavailable_rate(seeded_db):
    _account(seeded_db, "Crypto", Currency.USD)  # snapshot present but no rate anywhere
    acc = seeded_db.query(Account).filter(Account.name == "Crypto").first()
    _snapshot(seeded_db, acc.id, 100)
    seeded_db.commit()
    out = FinanceService(seeded_db).net_worth_rub(str(HOUSEHOLD_ID))
    assert out["any_unavailable"] is True


def test_net_worth_ignores_accounts_without_snapshot(seeded_db):
    _account(seeded_db, "Пустой", Currency.RUB)  # no snapshot → skipped
    rub = _account(seeded_db, "Нал", Currency.RUB)
    _snapshot(seeded_db, rub.id, 5000)
    seeded_db.commit()
    out = FinanceService(seeded_db).net_worth_rub(str(HOUSEHOLD_ID))
    assert out["total_rub"] == Decimal("5000")
