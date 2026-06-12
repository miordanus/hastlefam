import pytest
from decimal import Decimal
from datetime import date
from pydantic import ValidationError

from app.api.schemas.finance import TransactionCreate


BASE = dict(
    household_id="hid",
    amount=Decimal("100"),
    occurred_at=date(2026, 6, 12),
)


def test_amount_zero_rejected():
    with pytest.raises(ValidationError, match="greater than 0"):
        TransactionCreate(**{**BASE, "amount": Decimal("0")})


def test_amount_negative_rejected():
    with pytest.raises(ValidationError, match="greater than 0"):
        TransactionCreate(**{**BASE, "amount": Decimal("-50")})


def test_amount_positive_accepted():
    t = TransactionCreate(**BASE)
    assert t.amount == Decimal("100")


def test_invalid_direction_rejected():
    with pytest.raises(ValidationError, match="direction"):
        TransactionCreate(**{**BASE, "direction": "sideways"})


def test_valid_directions_accepted():
    for d in ("income", "expense", "exchange", "transfer"):
        t = TransactionCreate(**{**BASE, "direction": d})
        assert t.direction == d


def test_invalid_currency_rejected():
    with pytest.raises(ValidationError, match="currency"):
        TransactionCreate(**{**BASE, "currency": "GBP"})


def test_valid_currencies_accepted():
    for c in ("RUB", "USD", "USDT", "EUR", "AMD"):
        t = TransactionCreate(**{**BASE, "currency": c})
        assert t.currency == c


def test_merchant_blank_string_becomes_none():
    t = TransactionCreate(**{**BASE, "merchant": "   "})
    assert t.merchant is None


def test_merchant_padded_stripped():
    t = TransactionCreate(**{**BASE, "merchant": "  Biedronka  "})
    assert t.merchant == "Biedronka"


def test_merchant_none_stays_none():
    t = TransactionCreate(**{**BASE, "merchant": None})
    assert t.merchant is None


def test_currency_lowercase_normalized():
    t = TransactionCreate(**{**BASE, "currency": "rub"})
    assert t.currency == "RUB"
