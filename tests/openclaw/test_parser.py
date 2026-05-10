from datetime import date
from decimal import Decimal

import pytest

from openclaw.parser import parse

TODAY = date(2026, 5, 10)


def test_rub_default():
    rows = parse("500 кафе", today=TODAY)
    assert len(rows) == 1
    assert rows[0].currency == "RUB"


def test_inline_usd():
    rows = parse("500 USD кафе", today=TODAY)
    assert rows[0].currency == "USD"


def test_inline_eur():
    rows = parse("20 EUR ресторан", today=TODAY)
    assert rows[0].currency == "EUR"


def test_plus_prefix_income():
    rows = parse("+90000 зп", today=TODAY)
    assert rows[0].direction == "income"
    assert rows[0].amount == Decimal("90000")


def test_income_keyword_zp():
    rows = parse("90000 зп", today=TODAY)
    assert rows[0].direction == "income"


def test_income_keyword_salary():
    rows = parse("90000 salary May", today=TODAY)
    assert rows[0].direction == "income"


def test_default_direction_expense():
    rows = parse("350 продукты", today=TODAY)
    assert rows[0].direction == "expense"
    assert rows[0].is_internal_transfer is False


def test_transfer_keyword():
    rows = parse("5000 перевод на карту", today=TODAY)
    assert rows[0].direction == "expense"
    assert rows[0].is_internal_transfer is True


def test_exchange_keyword():
    rows = parse("1000 exchange USD", today=TODAY)
    assert rows[0].direction == "exchange"


def test_vchera_date():
    rows = parse("500 кафе вчера", today=TODAY)
    assert rows[0].date == date(2026, 5, 9)


def test_pozavchera_date():
    rows = parse("500 кафе позавчера", today=TODAY)
    assert rows[0].date == date(2026, 5, 8)


def test_dd_mm_date():
    rows = parse("12.03 350 продукты", today=TODAY)
    assert rows[0].date == date(2026, 3, 12)


def test_dd_mm_dash_date():
    rows = parse("12-03 350 продукты", today=TODAY)
    assert rows[0].date == date(2026, 3, 12)


def test_yyyy_mm_dd_date():
    rows = parse("2026-03-12 350 продукты", today=TODAY)
    assert rows[0].date == date(2026, 3, 12)


def test_no_date_defaults_to_today():
    rows = parse("350 продукты", today=TODAY)
    assert rows[0].date == TODAY


def test_missing_amount_needs_correction():
    rows = parse("продукты пятёрочка", today=TODAY)
    assert rows[0].parse_status == "needs_correction"
    assert rows[0].amount is None
    assert len(rows) == 1  # never dropped


def test_ok_status_when_amount_present():
    rows = parse("350 продукты", today=TODAY)
    assert rows[0].parse_status == "ok"


def test_planned_suffix():
    rows = parse("500 кафе [planned]", today=TODAY)
    assert rows[0].is_planned is True


def test_slash_separator():
    rows = parse("12.03 350 продукты / 14.03 +90000 зп", today=TODAY)
    assert len(rows) == 2
    assert rows[0].direction == "expense"
    assert rows[0].amount == Decimal("350")
    assert rows[1].direction == "income"
    assert rows[1].amount == Decimal("90000")


def test_newline_separator():
    rows = parse("350 продукты\n+90000 зп", today=TODAY)
    assert len(rows) == 2


def test_merchant_raw_is_remainder():
    rows = parse("12.03 350 пятёрочка", today=TODAY)
    assert rows[0].merchant_raw == "пятёрочка"


def test_empty_lines_skipped():
    rows = parse("350 кафе\n\n500 такси", today=TODAY)
    assert len(rows) == 2


def test_decimal_amount():
    rows = parse("1499.99 подписка", today=TODAY)
    assert rows[0].amount == Decimal("1499.99")
