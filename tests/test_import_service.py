import pytest
from decimal import Decimal
from datetime import datetime, timezone

from app.application.services.import_service import ImportService


def test_parse_decimal_valid():
    assert ImportService._parse_decimal("123.45") == Decimal("123.45")
    assert ImportService._parse_decimal(42) == Decimal("42")
    assert ImportService._parse_decimal("0") == Decimal("0")


def test_parse_decimal_none():
    assert ImportService._parse_decimal(None) is None


def test_parse_decimal_invalid():
    assert ImportService._parse_decimal("not-a-number") is None


def test_parse_dt_valid_iso():
    result = ImportService._parse_dt("2024-01-15T10:30:00Z")
    assert isinstance(result, datetime)
    assert result.year == 2024


def test_parse_dt_datetime_passthrough():
    dt = datetime.now(timezone.utc)
    assert ImportService._parse_dt(dt) is dt


def test_parse_dt_none():
    assert ImportService._parse_dt(None) is None


def test_parse_dt_invalid():
    assert ImportService._parse_dt("garbage") is None


def test_fingerprint_deterministic():
    fp1 = ImportService._fingerprint("h1", datetime(2024, 1, 1, tzinfo=timezone.utc), Decimal("100"), "shop", "src")
    fp2 = ImportService._fingerprint("h1", datetime(2024, 1, 1, tzinfo=timezone.utc), Decimal("100"), "shop", "src")
    assert fp1 == fp2


def test_fingerprint_differs_by_merchant():
    fp1 = ImportService._fingerprint("h1", datetime(2024, 1, 1, tzinfo=timezone.utc), Decimal("100"), "shop_a", "src")
    fp2 = ImportService._fingerprint("h1", datetime(2024, 1, 1, tzinfo=timezone.utc), Decimal("100"), "shop_b", "src")
    assert fp1 != fp2


def test_sql_injection_guard_rejects_delete(seeded_db):
    svc = ImportService(seeded_db)
    with pytest.raises(ValueError, match="Only SELECT"):
        svc.import_from_sql(
            household_id="test",
            source_name="test",
            sql_query="DELETE FROM transactions",
        )


def test_sql_injection_guard_rejects_drop(seeded_db):
    svc = ImportService(seeded_db)
    with pytest.raises(ValueError, match="Only SELECT"):
        svc.import_from_sql(
            household_id="test",
            source_name="test",
            sql_query="DROP TABLE transactions",
        )
