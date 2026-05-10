import dataclasses
from datetime import date
from decimal import Decimal
from unittest.mock import MagicMock

from openclaw.dedup import check
from openclaw.normalizer import NormalizedRow

HH_ID = "ed36b994-81e3-4fa0-b860-205381ba4681"


def _make_row(fp: str | None = "abc123", is_duplicate: bool = False) -> NormalizedRow:
    return NormalizedRow(
        raw_line="raw",
        date=date(2026, 3, 12),
        amount=Decimal("350"),
        currency="RUB",
        direction="expense",
        is_internal_transfer=False,
        is_planned=False,
        merchant_raw="кафе",
        description_raw="кафе",
        parse_status="ok",
        household_id=HH_ID,
        source="openclaw",
        occurred_at="2026-03-12T00:00:00+03:00",
        dedup_fingerprint=fp,
        primary_tag=None,
        is_duplicate=is_duplicate,
    )


def test_marks_duplicate_when_fingerprint_found():
    client = MagicMock()
    client.get.return_value = [{"id": "existing-uuid"}]
    rows = check([_make_row(fp="abc123")], client)
    assert rows[0].is_duplicate is True


def test_not_duplicate_when_no_match():
    client = MagicMock()
    client.get.return_value = []
    rows = check([_make_row(fp="abc123")], client)
    assert rows[0].is_duplicate is False


def test_no_check_when_fingerprint_is_none():
    client = MagicMock()
    rows = check([_make_row(fp=None)], client)
    assert rows[0].is_duplicate is False
    client.get.assert_not_called()


def test_get_called_with_correct_params():
    client = MagicMock()
    client.get.return_value = []
    check([_make_row(fp="myfp")], client)
    client.get.assert_called_once_with(
        "transactions",
        params={"dedup_fingerprint": "eq.myfp", "select": "id", "limit": "1"},
    )


def test_multiple_rows_checked_sequentially():
    client = MagicMock()
    client.get.side_effect = [[{"id": "x"}], []]
    rows = check([_make_row(fp="fp1"), _make_row(fp="fp2")], client)
    assert rows[0].is_duplicate is True
    assert rows[1].is_duplicate is False
    assert client.get.call_count == 2
