"""Tests for last-actual-rate balance valuation (Task 3).

The household values foreign-currency holdings at the *real* rate it last
applied in a RUB-paired exchange, not the ЦБ (CBR) rate. CBR is the fallback
when there is no such exchange.
"""
from __future__ import annotations

import uuid
from datetime import date, datetime, timezone
from decimal import Decimal

from app.application.services.fx_service import (
    last_applied_rate_to_rub,
    valuation_rate_to_rub,
)
from app.domain.enums import Currency, TransactionDirection
from app.infrastructure.db.models import FxRate, Transaction
from tests.conftest import HOUSEHOLD_ID


def _exchange(db, *, from_amount, from_cur, to_amount, to_cur, occurred_at):
    tx = Transaction(
        id=uuid.uuid4(),
        household_id=HOUSEHOLD_ID,
        direction=TransactionDirection.EXCHANGE,
        amount=Decimal(str(from_amount)),
        currency=Currency(from_cur.lower()) if from_cur.lower() in {c.value for c in Currency} else Currency.RUB,
        occurred_at=occurred_at,
        merchant_raw="test exchange",
        source="test",
        parse_status="ok",
        from_amount=Decimal(str(from_amount)),
        from_currency=from_cur,
        to_amount=Decimal(str(to_amount)),
        to_currency=to_cur,
        exchange_rate=Decimal(str(to_amount)) / Decimal(str(from_amount)),
        extra_tags=[],
        is_planned=False,
        is_internal_transfer=False,
        is_skipped=False,
    )
    db.add(tx)
    return tx


def _fx(db, *, from_cur, rate, on=date(2026, 5, 20)):
    db.add(FxRate(id=uuid.uuid4(), date=on, from_currency=from_cur, to_currency="RUB", rate=Decimal(str(rate))))


# ─── last_applied_rate_to_rub ────────────────────────────────────────────────

def test_last_applied_rate_from_rub_to_usd(seeded_db):
    # Bought 100 USD with 10000 RUB → 100 RUB per USD.
    _exchange(seeded_db, from_amount=10000, from_cur="RUB", to_amount=100, to_cur="USD",
              occurred_at=datetime(2026, 5, 10, tzinfo=timezone.utc))
    seeded_db.commit()
    assert last_applied_rate_to_rub(HOUSEHOLD_ID, "USD", seeded_db) == Decimal("100")


def test_last_applied_rate_from_usd_to_rub(seeded_db):
    # Sold 100 USD for 9500 RUB → 95 RUB per USD.
    _exchange(seeded_db, from_amount=100, from_cur="USD", to_amount=9500, to_cur="RUB",
              occurred_at=datetime(2026, 5, 10, tzinfo=timezone.utc))
    seeded_db.commit()
    assert last_applied_rate_to_rub(HOUSEHOLD_ID, "USD", seeded_db) == Decimal("95")


def test_last_applied_rate_uses_most_recent(seeded_db):
    _exchange(seeded_db, from_amount=10000, from_cur="RUB", to_amount=100, to_cur="USD",
              occurred_at=datetime(2026, 5, 1, tzinfo=timezone.utc))   # 100 RUB/USD
    _exchange(seeded_db, from_amount=10500, from_cur="RUB", to_amount=100, to_cur="USD",
              occurred_at=datetime(2026, 5, 20, tzinfo=timezone.utc))  # 105 RUB/USD (latest)
    seeded_db.commit()
    assert last_applied_rate_to_rub(HOUSEHOLD_ID, "USD", seeded_db) == Decimal("105")


def test_last_applied_rate_none_without_rub_pair(seeded_db):
    # USDT↔EUR exchange does not pin a RUB rate for either side.
    _exchange(seeded_db, from_amount=250, from_cur="USDT", to_amount=230, to_cur="EUR",
              occurred_at=datetime(2026, 5, 10, tzinfo=timezone.utc))
    seeded_db.commit()
    assert last_applied_rate_to_rub(HOUSEHOLD_ID, "USD", seeded_db) is None


def test_last_applied_rate_rub_is_one(seeded_db):
    assert last_applied_rate_to_rub(HOUSEHOLD_ID, "RUB", seeded_db) == Decimal("1")


# ─── valuation_rate_to_rub (actual preferred, CBR fallback) ──────────────────

def test_valuation_prefers_actual_over_cbr(seeded_db):
    _exchange(seeded_db, from_amount=10000, from_cur="RUB", to_amount=100, to_cur="USD",
              occurred_at=datetime(2026, 5, 10, tzinfo=timezone.utc))  # 100 RUB/USD actual
    _fx(seeded_db, from_cur="USD", rate=70)  # CBR says 70
    seeded_db.commit()
    rate, source = valuation_rate_to_rub(HOUSEHOLD_ID, "USD", date(2026, 5, 20), seeded_db)
    assert rate == Decimal("100")
    assert source == "actual"


def test_valuation_falls_back_to_cbr(seeded_db):
    _fx(seeded_db, from_cur="USD", rate=70)
    seeded_db.commit()
    rate, source = valuation_rate_to_rub(HOUSEHOLD_ID, "USD", date(2026, 5, 20), seeded_db)
    assert rate == Decimal("70")
    assert source == "cbr"


def test_valuation_rub_passthrough(seeded_db):
    rate, source = valuation_rate_to_rub(HOUSEHOLD_ID, "RUB", date(2026, 5, 20), seeded_db)
    assert rate == Decimal("1")
    assert source == "rub"


def test_valuation_none_when_no_data(seeded_db):
    rate, source = valuation_rate_to_rub(HOUSEHOLD_ID, "USD", date(2026, 5, 20), seeded_db)
    assert rate is None
    assert source == "none"
