"""Real exchange-rate valuation: per-transaction override > real applied rate
(date-aware, from RUB-paired EXCHANGE txns) > CBR.

Covers fx_service.valuation_rate_to_rub / last_applied_rate_to_rub, the REST
mirror helpers (_build_applied_lookup / _real_rate_on_date), and that the
clear-picture hustle inputs value USDT income at the real rate, not CBR.
"""
from __future__ import annotations

import uuid
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

from app.application.services.fx_service import (
    last_applied_rate_to_rub,
    valuation_rate_to_rub,
)
from app.application.services.finance_service import (
    FinanceService,
    _build_applied_lookup,
    _real_rate_on_date,
)
from app.domain.enums import Currency, TransactionDirection
from app.infrastructure.db.models import Account, BalanceSnapshot, FxRate, Transaction
from tests.conftest import ACCOUNT_ID, HOUSEHOLD_ID, USER_ID


def _exchange(db, *, from_amount, from_cur, to_amount, to_cur, days_ago):
    when = datetime.now(timezone.utc) - timedelta(days=days_ago)
    db.add(Transaction(
        id=uuid.uuid4(), household_id=HOUSEHOLD_ID, direction=TransactionDirection.EXCHANGE,
        amount=Decimal(str(from_amount)), currency=Currency.RUB, occurred_at=when,
        merchant_raw="x", source="test", parse_status="ok", extra_tags=[],
        from_amount=Decimal(str(from_amount)), from_currency=from_cur,
        to_amount=Decimal(str(to_amount)), to_currency=to_cur,
        exchange_rate=Decimal(str(to_amount)) / Decimal(str(from_amount)),
        is_planned=False, is_internal_transfer=False, is_skipped=False))


def _income(db, amount, currency, days_ago, override=None):
    db.add(Transaction(
        id=uuid.uuid4(), household_id=HOUSEHOLD_ID, user_id=USER_ID,
        direction=TransactionDirection.INCOME, amount=Decimal(str(amount)), currency=currency,
        occurred_at=datetime.now(timezone.utc) - timedelta(days=days_ago),
        merchant_raw="pay", source="test", parse_status="ok", extra_tags=[],
        primary_tag="доход", is_planned=False, is_internal_transfer=False, is_skipped=False,
        applied_rate_override=Decimal(str(override)) if override is not None else None))


# ─── fx_service precedence ────────────────────────────────────────────────────

def test_valuation_prefers_override(seeded_db):
    _exchange(seeded_db, from_amount=1000, from_cur="USDT", to_amount=80000, to_cur="RUB", days_ago=5)
    seeded_db.commit()
    rate, src = valuation_rate_to_rub(str(HOUSEHOLD_ID), "USDT", date.today(), seeded_db,
                                     override=Decimal("90"))
    assert (rate, src) == (Decimal("90"), "override")


def test_valuation_uses_applied_over_cbr(seeded_db):
    _exchange(seeded_db, from_amount=1000, from_cur="USDT", to_amount=80000, to_cur="RUB", days_ago=5)
    seeded_db.add(FxRate(id=uuid.uuid4(), date=date.today(), from_currency="USDT",
                         to_currency="RUB", rate=Decimal("73")))
    seeded_db.commit()
    rate, src = valuation_rate_to_rub(str(HOUSEHOLD_ID), "USDT", date.today(), seeded_db)
    assert src == "actual"
    assert rate == Decimal("80")  # 80000/1000, the real applied rate, not CBR 73


def test_valuation_falls_back_to_cbr(seeded_db):
    seeded_db.add(FxRate(id=uuid.uuid4(), date=date.today(), from_currency="USD",
                         to_currency="RUB", rate=Decimal("73")))
    seeded_db.commit()
    rate, src = valuation_rate_to_rub(str(HOUSEHOLD_ID), "USD", date.today(), seeded_db)
    assert src == "cbr"
    assert rate == Decimal("73")


def test_last_applied_is_date_aware(seeded_db):
    _exchange(seeded_db, from_amount=1000, from_cur="USDT", to_amount=78000, to_cur="RUB", days_ago=60)
    _exchange(seeded_db, from_amount=1000, from_cur="USDT", to_amount=72000, to_cur="RUB", days_ago=5)
    seeded_db.commit()
    today = date.today()
    # As of 30 days ago only the ₽78 exchange had happened.
    old = last_applied_rate_to_rub(str(HOUSEHOLD_ID), "USDT", seeded_db, for_date=today - timedelta(days=30))
    assert old == Decimal("78")
    # As of today, the most recent ₽72 exchange wins.
    new = last_applied_rate_to_rub(str(HOUSEHOLD_ID), "USDT", seeded_db, for_date=today)
    assert new == Decimal("72")


# ─── REST mirror helpers (pure) ───────────────────────────────────────────────

def test_build_applied_lookup_and_rate_on_date():
    rows = [
        {"occurred_at": "2026-05-08", "from_amount": "1000", "from_currency": "USDT",
         "to_amount": "72670", "to_currency": "RUB"},
        {"occurred_at": "2026-03-13", "from_amount": "1000", "from_currency": "USDT",
         "to_amount": "77500", "to_currency": "RUB"},
    ]
    applied = _build_applied_lookup(rows)
    assert applied["USDT"][0][0] == "2026-05-08"  # sorted desc
    # date-aware: a March txn values at the March rate, not May's
    assert _real_rate_on_date("USDT", "2026-03-20", applied, {}) == 77.5
    assert _real_rate_on_date("USDT", "2026-06-01", applied, {}) == 72.67
    # override wins
    assert _real_rate_on_date("USDT", "2026-06-01", applied, {}, override=90.0) == 90.0
    # RUB is always 1; unknown currency with no data → None
    assert _real_rate_on_date("RUB", "2026-06-01", applied, {}) == 1.0
    assert _real_rate_on_date("EUR", "2026-06-01", applied, {}) is None


# ─── clear-picture hustle income uses the real rate ───────────────────────────

def test_hustle_income_uses_real_rate_not_cbr(seeded_db):
    seeded_db.add(BalanceSnapshot(id=uuid.uuid4(), account_id=ACCOUNT_ID, household_id=HOUSEHOLD_ID,
                                  actual_balance=Decimal("0"), created_at=datetime.now(timezone.utc)))
    _exchange(seeded_db, from_amount=1000, from_cur="USDT", to_amount=80000, to_cur="RUB", days_ago=20)
    _income(seeded_db, 300, Currency.USDT, days_ago=10)  # 300 USDT income, real rate 80
    seeded_db.add(FxRate(id=uuid.uuid4(), date=date.today(), from_currency="USDT",
                         to_currency="RUB", rate=Decimal("73")))  # CBR would undervalue
    seeded_db.commit()
    out = FinanceService(seeded_db).data_health(str(HOUSEHOLD_ID))
    # 300 × 80 / 3 trailing months = 8000, not 300×73/3=7300
    assert out["clear_picture"]["hustle"]["expected_income_rub"] == 8000.0


def test_hustle_income_honors_per_txn_override(seeded_db):
    seeded_db.add(BalanceSnapshot(id=uuid.uuid4(), account_id=ACCOUNT_ID, household_id=HOUSEHOLD_ID,
                                  actual_balance=Decimal("0"), created_at=datetime.now(timezone.utc)))
    _income(seeded_db, 300, Currency.USDT, days_ago=10, override=90)  # forced ₽90/USDT
    seeded_db.commit()
    out = FinanceService(seeded_db).data_health(str(HOUSEHOLD_ID))
    assert out["clear_picture"]["hustle"]["expected_income_rub"] == 9000.0  # 300×90/3
