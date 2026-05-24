"""Unit tests for the per-date FX helpers in finance_service.

Helpers are pure: no DB, no settings. Tests pin the contract the *_via_rest
methods rely on when converting foreign-currency rows to RUB.
"""
from app.application.services.finance_service import _build_fx_lookup, _rub_on_date


def test_build_fx_lookup_empty():
    assert _build_fx_lookup([]) == {}


def test_build_fx_lookup_sorts_desc_per_currency():
    rows = [
        {"from_currency": "USD", "rate": 73.0, "date": "2026-05-20"},
        {"from_currency": "USD", "rate": 71.0, "date": "2026-05-22"},
        {"from_currency": "USD", "rate": 70.0, "date": "2026-05-21"},
        {"from_currency": "EUR", "rate": 85.0, "date": "2026-05-20"},
    ]
    lookup = _build_fx_lookup(rows)
    assert list(lookup.keys()) == ["usd", "eur"] or set(lookup.keys()) == {"usd", "eur"}
    assert lookup["usd"] == [("2026-05-22", 71.0), ("2026-05-21", 70.0), ("2026-05-20", 73.0)]
    assert lookup["eur"] == [("2026-05-20", 85.0)]


def test_build_fx_lookup_skips_rows_missing_currency():
    rows = [
        {"from_currency": "", "rate": 1.0, "date": "2026-01-01"},
        {"from_currency": None, "rate": 1.0, "date": "2026-01-01"},
        {"from_currency": "USD", "rate": 70.0, "date": "2026-01-01"},
    ]
    lookup = _build_fx_lookup(rows)
    assert lookup == {"usd": [("2026-01-01", 70.0)]}


def _sample_fx():
    return _build_fx_lookup([
        {"from_currency": "USD", "rate": 70.0, "date": "2026-05-20"},
        {"from_currency": "USD", "rate": 81.0, "date": "2026-04-01"},
        {"from_currency": "EUR", "rate": 85.0, "date": "2026-05-20"},
    ])


def test_rub_on_date_rub_passthrough():
    # RUB never depends on FX or date.
    assert _rub_on_date(100.0, "RUB", "2026-05-20", _sample_fx()) == 100.0
    assert _rub_on_date(100.0, "rub", None, _sample_fx()) == 100.0


def test_rub_on_date_usdt_aliases_to_usd():
    # USDT shares USD's rate row.
    assert _rub_on_date(1.0, "USDT", "2026-05-20", _sample_fx()) == 70.0
    assert _rub_on_date(1.0, "usdt", "2026-04-01", _sample_fx()) == 81.0


def test_rub_on_date_exact_date_hit():
    assert _rub_on_date(1.0, "USD", "2026-04-01", _sample_fx()) == 81.0
    assert _rub_on_date(1.0, "USD", "2026-05-20", _sample_fx()) == 70.0


def test_rub_on_date_7day_backward_fallback():
    # Tx on 2026-04-05 should pick up the 2026-04-01 rate (4-day backward).
    assert _rub_on_date(1.0, "USD", "2026-04-05", _sample_fx()) == 81.0


def test_rub_on_date_8day_gap_silent_fallback():
    # Tx on 2026-04-09 is 8 days after 2026-04-01 — outside window. Falls back to 1.0.
    assert _rub_on_date(123.0, "USD", "2026-04-09", _sample_fx()) == 123.0


def test_rub_on_date_no_date_uses_latest():
    # Empty / None occurred_date uses per-currency latest rate.
    fx = _sample_fx()
    assert _rub_on_date(1.0, "USD", "", fx) == 70.0
    assert _rub_on_date(1.0, "USD", None, fx) == 70.0


def test_rub_on_date_unknown_currency_returns_amount():
    # No rates for PLN in the sample — silent 1:1.
    assert _rub_on_date(42.0, "PLN", "2026-05-20", _sample_fx()) == 42.0


def test_rub_on_date_iso_with_time_uses_only_date_prefix():
    # Full ISO timestamp: helper slices to the first 10 chars.
    assert _rub_on_date(1.0, "USD", "2026-04-01T12:34:56+00:00", _sample_fx()) == 81.0


def test_rub_on_date_invalid_date_string_falls_back_to_1():
    # Non-ISO garbage in occurred_date — try-block fails, no rate matches → 1:1.
    assert _rub_on_date(50.0, "USD", "not-a-date", _sample_fx()) == 50.0
