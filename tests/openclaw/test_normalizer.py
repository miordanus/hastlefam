import dataclasses
import hashlib
from datetime import date
from decimal import Decimal
from unittest.mock import MagicMock

import pytest

from openclaw.normalizer import NormalizedRow, normalize, _compute_fingerprint
from openclaw.parser import ParsedRow

HH_ID = "ed36b994-81e3-4fa0-b860-205381ba4681"


def _make_client(tags: list[str] | None = None) -> MagicMock:
    client = MagicMock()
    client.household_id = HH_ID
    client.get.return_value = [{"primary_tag": t} for t in (tags or [])]
    return client


def _make_parsed(
    amount: Decimal | None = Decimal("350"),
    merchant: str = "пятёрочка",
    direction: str = "expense",
    d: date = date(2026, 3, 12),
    parse_status: str = "ok",
) -> ParsedRow:
    return ParsedRow(
        raw_line="raw",
        date=d,
        amount=amount,
        currency="RUB",
        direction=direction,
        is_internal_transfer=False,
        is_planned=False,
        merchant_raw=merchant,
        description_raw=merchant,
        parse_status=parse_status,
    )


def test_fingerprint_exact_format():
    fp = _compute_fingerprint(HH_ID, date(2026, 3, 12), Decimal("350"), "RUB", "пятёрочка", "expense")
    expected = hashlib.sha256(
        f"{HH_ID}|2026-03-12|350.00|RUB|пятёрочка|expense|openclaw".encode()
    ).hexdigest()
    assert fp == expected


def test_occurred_at_timezone():
    client = _make_client()
    rows = normalize([_make_parsed(d=date(2026, 3, 12))], client)
    assert rows[0].occurred_at == "2026-03-12T00:00:00+03:00"


def test_source_is_always_openclaw():
    client = _make_client()
    rows = normalize([_make_parsed()], client)
    assert rows[0].source == "openclaw"


def test_household_id_from_client():
    client = _make_client()
    rows = normalize([_make_parsed()], client)
    assert rows[0].household_id == HH_ID


def test_known_tag_exact_match():
    client = _make_client(tags=["groceries", "пятёрочка"])
    rows = normalize([_make_parsed(merchant="пятёрочка")], client)
    assert rows[0].primary_tag == "пятёрочка"


def test_tag_match_case_insensitive():
    client = _make_client(tags=["пятёрочка"])
    rows = normalize([_make_parsed(merchant="ПЯТЁРОЧКА")], client)
    assert rows[0].primary_tag == "пятёрочка"


def test_no_tag_match():
    client = _make_client(tags=["groceries"])
    rows = normalize([_make_parsed(merchant="кафе рандом")], client)
    assert rows[0].primary_tag is None


def test_none_amount_no_fingerprint():
    client = _make_client()
    rows = normalize([_make_parsed(amount=None, parse_status="needs_correction")], client)
    assert rows[0].dedup_fingerprint is None


def test_none_date_uses_today(monkeypatch):
    import openclaw.normalizer as mod
    fixed = date(2026, 5, 10)
    monkeypatch.setattr(mod, "_today", lambda: fixed)
    client = _make_client()
    row = dataclasses.replace(_make_parsed(), date=None)
    rows = normalize([row], client)
    assert rows[0].occurred_at == "2026-05-10T00:00:00+03:00"


def test_is_duplicate_defaults_false():
    client = _make_client()
    rows = normalize([_make_parsed()], client)
    assert rows[0].is_duplicate is False


def test_tag_fetch_called_once_for_multiple_rows():
    client = _make_client(tags=["groceries"])
    normalize([_make_parsed(), _make_parsed(merchant="такси")], client)
    assert client.get.call_count == 1
