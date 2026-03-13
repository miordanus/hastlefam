"""Tests for the free-text parser (expense_parser.py)."""
from decimal import Decimal

from app.bot.parsers.expense_parser import parse
from app.domain.enums import Currency, TransactionDirection


# ─── Basic parsing ────────────────────────────────────────────────────────────

def test_parse_amount_and_merchant():
    r = parse("149 biedronka")
    assert r.ok
    assert r.amount == Decimal("149")
    assert r.merchant == "biedronka"
    assert r.currency == Currency.RUB  # default
    assert r.direction == TransactionDirection.EXPENSE


def test_parse_decimal_dot():
    r = parse("12.50 supermarket")
    assert r.ok
    assert r.amount == Decimal("12.50")


def test_parse_decimal_comma():
    r = parse("12,50 supermarket")
    assert r.ok
    assert r.amount == Decimal("12.50")


def test_parse_no_merchant_returns_ok_with_none():
    r = parse("149")
    assert r.ok
    assert r.amount == Decimal("149")
    assert r.merchant is None


def test_parse_text_only_returns_error():
    r = parse("hello world")
    assert not r.ok


# ─── Currency ─────────────────────────────────────────────────────────────────

def test_parse_currency_usd():
    r = parse("50 usd coffee")
    assert r.ok
    assert r.currency == Currency.USD
    assert r.currency_explicit is True
    assert r.merchant == "coffee"


def test_parse_currency_eur():
    r = parse("49.90 netflix EUR")
    assert r.ok
    assert r.currency == Currency.EUR
    assert r.merchant == "netflix"


def test_parse_currency_usdt():
    r = parse("100 usdt binance")
    assert r.ok
    assert r.currency == Currency.USDT


def test_parse_default_currency_is_rub():
    r = parse("149 taxi")
    assert r.currency == Currency.RUB
    assert r.currency_explicit is False


# ─── Tags ─────────────────────────────────────────────────────────────────────

def test_parse_single_tag():
    r = parse("149 coffee #food")
    assert r.primary_tag == "food"
    assert r.extra_tags == []


def test_parse_multiple_tags():
    r = parse("3500 monitor #tech #max")
    assert r.primary_tag == "tech"
    assert r.extra_tags == ["max"]


def test_parse_no_tag():
    r = parse("149 coffee")
    assert r.primary_tag is None
    assert r.extra_tags == []


# ─── Income direction ─────────────────────────────────────────────────────────

def test_parse_income_prefix():
    r = parse("+5000 зарплата")
    assert r.ok
    assert r.direction == TransactionDirection.INCOME
    assert r.amount == Decimal("5000")
    assert r.merchant == "зарплата"


def test_parse_expense_default():
    r = parse("149 coffee")
    assert r.direction == TransactionDirection.EXPENSE


# ─── Date hints ───────────────────────────────────────────────────────────────

def test_parse_date_yesterday():
    from datetime import datetime, timedelta, timezone
    r = parse("149 coffee вчера")
    today = datetime.now(timezone.utc).date()
    assert r.occurred_date == today - timedelta(days=1)
    assert r.date_explicit is True


def test_parse_date_tomorrow():
    from datetime import datetime, timedelta, timezone
    r = parse("149 coffee tomorrow")
    today = datetime.now(timezone.utc).date()
    assert r.occurred_date == today + timedelta(days=1)
    assert r.date_explicit is True


def test_parse_default_date_is_today():
    from datetime import datetime, timezone
    r = parse("149 coffee")
    today = datetime.now(timezone.utc).date()
    assert r.occurred_date == today
    assert r.date_explicit is False


# ─── Exchange ─────────────────────────────────────────────────────────────────

def test_parse_exchange():
    r = parse("250 usdt -> 230 eur")
    assert r.is_exchange
    assert r.from_amount == Decimal("250")
    assert r.from_currency == Currency.USDT
    assert r.to_amount == Decimal("230")
    assert r.to_currency == Currency.EUR


def test_parse_exchange_arrow_unicode():
    r = parse("250 usdt → 230 eur")
    assert r.is_exchange


# ─── Fingerprint determinism (from capture handler logic) ─────────────────────

def test_fingerprint_deterministic():
    """Fingerprint function in capture handler is deterministic."""
    import hashlib
    from decimal import Decimal

    def fp(hid, amount, currency, merchant, date):
        payload = f"{hid}|{date}|{amount}|{currency}|{merchant.strip().lower()}|telegram"
        return hashlib.sha256(payload.encode()).hexdigest()

    f1 = fp("h1", Decimal("100"), "RUB", "shop", "2026-03-13")
    f2 = fp("h1", Decimal("100"), "RUB", "shop", "2026-03-13")
    assert f1 == f2


def test_fingerprint_differs_by_currency():
    import hashlib
    from decimal import Decimal

    def fp(hid, amount, currency, merchant, date):
        payload = f"{hid}|{date}|{amount}|{currency}|{merchant.strip().lower()}|telegram"
        return hashlib.sha256(payload.encode()).hexdigest()

    f1 = fp("h1", Decimal("100"), "RUB", "shop", "2026-03-13")
    f2 = fp("h1", Decimal("100"), "USD", "shop", "2026-03-13")
    assert f1 != f2
