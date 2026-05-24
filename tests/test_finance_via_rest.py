"""Integration tests for the REST-mode finance service methods.

Use the `mock_supabase` fixture from conftest to preload table contents;
the patched SupabaseClient returns those rows verbatim regardless of the
PostgREST-style filters the methods pass. Tests load only the rows the
specific query needs (e.g. snapshots dated *before* month-start for the
'anchor' query, since the mock doesn't apply filters).

What's locked down here:
- per-date FX: snapshots convert at snapshot date, transactions at occurred_at
- balance_value_rub = start_balance_rub + actual_delta
- forecast_eom_rub semantics (current / past / future month)
- planned + overdue handling
- exclusions (internal_transfer, exchange, is_skipped)
"""
from datetime import date
from unittest.mock import patch

import pytest

from app.application.services.finance_service import FinanceService


HID = "00000000-0000-4000-8000-000000000001"
ACC_RUB = "00000000-0000-4000-8000-000000000100"
ACC_USDT = "00000000-0000-4000-8000-000000000101"


def _account(aid, currency, name="A"):
    return {"id": aid, "name": name, "currency": currency, "is_active": True}


def _snap(account_id, balance, created_at):
    return {"account_id": account_id, "actual_balance": balance, "created_at": created_at}


def _tx(
    *,
    direction,
    amount,
    occurred_at,
    currency="RUB",
    is_planned=False,
    is_internal_transfer=False,
    is_skipped=False,
    primary_tag=None,
    merchant_raw="",
    account_id=None,
    tx_id="00000000-0000-4000-8000-000000099999",
):
    return {
        "id": tx_id,
        "occurred_at": occurred_at,
        "direction": direction,
        "amount": amount,
        "currency": currency,
        "merchant_raw": merchant_raw,
        "primary_tag": primary_tag,
        "account_id": account_id,
        "is_planned": is_planned,
        "is_internal_transfer": is_internal_transfer,
        "is_skipped": is_skipped,
    }


def _fx(currency, date_, rate):
    return {"from_currency": currency, "to_currency": "RUB", "rate": rate, "date": date_}


def _freeze_today(d):
    """Replace date.today() inside finance_service with a fixed date."""
    class _D:
        @staticmethod
        def today():
            return d
        # delegate everything else
        fromisoformat = staticmethod(date.fromisoformat)
    return patch("app.application.services.finance_service.date", _D)


# ════════════════════════════════════════════════════════════════════════
# monthly_report_via_rest
# ════════════════════════════════════════════════════════════════════════

def test_monthly_report_empty(mock_supabase):
    mock_supabase.tables = {"accounts": [], "transactions": [], "balance_snapshots": [], "fx_rates": []}
    out = FinanceService(None).monthly_report_via_rest(HID, 2026, 5)
    assert out["balance_value_rub"] == 0
    assert out["start_balance_rub"] == 0
    assert out["forecast_eom_rub"] == 0
    assert out["transactions"] == []


def test_start_balance_uses_per_date_fx(mock_supabase):
    """USDT snapshot anchored Apr 1 at rate 80; today's rate 70. Start balance must use 80."""
    mock_supabase.tables = {
        "accounts": [_account(ACC_USDT, "USDT")],
        "transactions": [],
        "balance_snapshots": [_snap(ACC_USDT, 100.0, "2026-04-01T00:00:00+00")],
        "fx_rates": [
            _fx("USD", "2026-05-20", 70.0),  # latest
            _fx("USD", "2026-04-01", 80.0),  # snapshot date
        ],
    }
    with _freeze_today(date(2026, 5, 24)):
        out = FinanceService(None).monthly_report_via_rest(HID, 2026, 5)
    # 100 USDT × 80 (snapshot date) = 8000, NOT 100 × 70 = 7000
    assert out["start_balance_rub"] == 8000.0


def test_actual_income_uses_per_date_fx(mock_supabase):
    """USDT income on Apr 12 at rate 76; latest 70 (rate 76 must win)."""
    mock_supabase.tables = {
        "accounts": [_account(ACC_USDT, "USDT")],
        "transactions": [_tx(direction="income", amount=10.0, currency="USDT", occurred_at="2026-04-12T00:00:00+00")],
        "balance_snapshots": [_snap(ACC_USDT, 0.0, "2026-04-01T00:00:00+00")],
        "fx_rates": [
            _fx("USD", "2026-05-20", 70.0),  # latest
            _fx("USD", "2026-04-12", 76.0),
            _fx("USD", "2026-04-01", 80.0),
        ],
    }
    with _freeze_today(date(2026, 5, 24)):
        out = FinanceService(None).monthly_report_via_rest(HID, 2026, 4)
    # delta_rub = 10 × 76 = 760
    assert out["balance_value_rub"] == 760.0


def test_planned_future_in_current_month_only_to_forecast(mock_supabase):
    """Planned tx on May 30 (today=May 24) → forecast, not delta."""
    mock_supabase.tables = {
        "accounts": [_account(ACC_RUB, "RUB")],
        "transactions": [_tx(direction="expense", amount=500.0, occurred_at="2026-05-30T00:00:00+00", is_planned=True)],
        "balance_snapshots": [_snap(ACC_RUB, 1000.0, "2026-05-01T00:00:00+00")],
        "fx_rates": [],
    }
    with _freeze_today(date(2026, 5, 24)):
        out = FinanceService(None).monthly_report_via_rest(HID, 2026, 5)
    assert out["balance_value_rub"] == 1000.0  # planned does NOT enter delta
    assert out["forecast_eom_rub"] == 500.0    # 1000 - 500


@pytest.mark.xfail(strict=True, reason="Bug #2 — overdue planned currently dropped; fixed in follow-up commit")
def test_overdue_planned_counted_in_forecast(mock_supabase):
    """Planned tx on May 10 (today=May 24, current month) — overdue.

    LOCKS THE INVARIANT after Bug #2 fix: overdue planned still belongs to EOM
    forecast (the row 'should' happen this month; it hasn't materialised yet).
    """
    mock_supabase.tables = {
        "accounts": [_account(ACC_RUB, "RUB")],
        "transactions": [_tx(direction="expense", amount=500.0, occurred_at="2026-05-10T00:00:00+00", is_planned=True)],
        "balance_snapshots": [_snap(ACC_RUB, 1000.0, "2026-05-01T00:00:00+00")],
        "fx_rates": [],
    }
    with _freeze_today(date(2026, 5, 24)):
        out = FinanceService(None).monthly_report_via_rest(HID, 2026, 5)
    assert out["balance_value_rub"] == 1000.0
    assert out["forecast_eom_rub"] == 500.0    # overdue still subtracted


def test_internal_transfer_excluded_from_delta_and_forecast(mock_supabase):
    """is_internal_transfer=true rows leak into nothing.

    Note: the actual REST query already filters is_internal_transfer=eq.false,
    but the mock doesn't apply filters — so this test verifies the in-Python
    safety net (the `if tx.get('is_internal_transfer'): continue` line).
    """
    mock_supabase.tables = {
        "accounts": [_account(ACC_RUB, "RUB")],
        "transactions": [_tx(direction="income", amount=999.0, occurred_at="2026-05-10T00:00:00+00", is_internal_transfer=True)],
        "balance_snapshots": [_snap(ACC_RUB, 500.0, "2026-05-01T00:00:00+00")],
        "fx_rates": [],
    }
    with _freeze_today(date(2026, 5, 24)):
        out = FinanceService(None).monthly_report_via_rest(HID, 2026, 5)
    assert out["balance_value_rub"] == 500.0
    assert out["forecast_eom_rub"] == 500.0


def test_exchange_direction_excluded(mock_supabase):
    """direction='exchange' rows don't move balance."""
    mock_supabase.tables = {
        "accounts": [_account(ACC_RUB, "RUB")],
        "transactions": [_tx(direction="exchange", amount=999.0, occurred_at="2026-05-10T00:00:00+00")],
        "balance_snapshots": [_snap(ACC_RUB, 500.0, "2026-05-01T00:00:00+00")],
        "fx_rates": [],
    }
    with _freeze_today(date(2026, 5, 24)):
        out = FinanceService(None).monthly_report_via_rest(HID, 2026, 5)
    assert out["balance_value_rub"] == 500.0


def test_past_month_forecast_eq_balance(mock_supabase):
    """For a past month, planned rows don't contribute to forecast."""
    mock_supabase.tables = {
        "accounts": [_account(ACC_RUB, "RUB")],
        "transactions": [
            _tx(direction="expense", amount=200.0, occurred_at="2026-03-10T00:00:00+00"),       # actual
            _tx(direction="expense", amount=500.0, occurred_at="2026-03-25T00:00:00+00", is_planned=True),  # planned in past
        ],
        "balance_snapshots": [_snap(ACC_RUB, 1000.0, "2026-03-01T00:00:00+00")],
        "fx_rates": [],
    }
    with _freeze_today(date(2026, 5, 24)):
        out = FinanceService(None).monthly_report_via_rest(HID, 2026, 3)
    assert out["balance_value_rub"] == 800.0      # 1000 - 200 (planned ignored)
    assert out["forecast_eom_rub"] == 800.0       # past month: forecast == balance


def test_future_month_forecast_includes_all_planned_in_month(mock_supabase):
    """For a future month, all in-month planned rows hit the forecast."""
    mock_supabase.tables = {
        "accounts": [_account(ACC_RUB, "RUB")],
        "transactions": [
            _tx(direction="income", amount=1000.0, occurred_at="2026-07-15T00:00:00+00", is_planned=True),
            _tx(direction="expense", amount=300.0, occurred_at="2026-07-20T00:00:00+00", is_planned=True),
        ],
        "balance_snapshots": [_snap(ACC_RUB, 100.0, "2026-07-01T00:00:00+00")],
        "fx_rates": [],
    }
    with _freeze_today(date(2026, 5, 24)):
        out = FinanceService(None).monthly_report_via_rest(HID, 2026, 7)
    assert out["balance_value_rub"] == 100.0
    assert out["forecast_eom_rub"] == 800.0       # 100 + 1000 - 300


def test_actual_after_today_in_current_month_held_back(mock_supabase):
    """Non-planned tx dated in the future of the current month: NOT in delta."""
    mock_supabase.tables = {
        "accounts": [_account(ACC_RUB, "RUB")],
        "transactions": [_tx(direction="expense", amount=99.0, occurred_at="2026-05-30T00:00:00+00")],
        "balance_snapshots": [_snap(ACC_RUB, 200.0, "2026-05-01T00:00:00+00")],
        "fx_rates": [],
    }
    with _freeze_today(date(2026, 5, 24)):
        out = FinanceService(None).monthly_report_via_rest(HID, 2026, 5)
    assert out["balance_value_rub"] == 200.0


# ════════════════════════════════════════════════════════════════════════
# monthly_totals_via_rest
# ════════════════════════════════════════════════════════════════════════

def test_monthly_totals_buckets_by_year_month(mock_supabase):
    mock_supabase.tables = {
        "transactions": [
            _tx(direction="income",  amount=100.0, occurred_at="2026-03-15T00:00:00+00"),
            _tx(direction="expense", amount=40.0,  occurred_at="2026-04-02T00:00:00+00"),
        ],
        "fx_rates": [],
    }
    out = FinanceService(None).monthly_totals_via_rest(HID, "2026-03", "2026-04")
    assert len(out) == 2
    by_mo = {(r["y"], r["mo"]): r for r in out}
    assert by_mo[(2026, 3)]["actual_income_rub"] == 100.0
    assert by_mo[(2026, 4)]["actual_expense_rub"] == 40.0


def test_monthly_totals_actual_vs_planned_split(mock_supabase):
    mock_supabase.tables = {
        "transactions": [
            _tx(direction="income", amount=70.0, occurred_at="2026-05-10T00:00:00+00"),
            _tx(direction="income", amount=30.0, occurred_at="2026-05-25T00:00:00+00", is_planned=True),
        ],
        "fx_rates": [],
    }
    out = FinanceService(None).monthly_totals_via_rest(HID, "2026-05", "2026-05")
    assert out[0]["actual_income_rub"] == 70.0
    assert out[0]["planned_income_rub"] == 30.0


def test_monthly_totals_per_date_fx(mock_supabase):
    """Two USDT income rows on different dates convert at different rates."""
    mock_supabase.tables = {
        "transactions": [
            _tx(direction="income", amount=10.0, currency="USDT", occurred_at="2026-04-12T00:00:00+00"),
            _tx(direction="income", amount=10.0, currency="USDT", occurred_at="2026-05-06T00:00:00+00"),
        ],
        "fx_rates": [
            _fx("USD", "2026-05-06", 72.0),
            _fx("USD", "2026-04-12", 76.0),
        ],
    }
    out = FinanceService(None).monthly_totals_via_rest(HID, "2026-04", "2026-05")
    by_mo = {(r["y"], r["mo"]): r for r in out}
    assert by_mo[(2026, 4)]["actual_income_rub"] == 760.0   # 10 × 76
    assert by_mo[(2026, 5)]["actual_income_rub"] == 720.0   # 10 × 72


# ════════════════════════════════════════════════════════════════════════
# category_movers_via_rest
# ════════════════════════════════════════════════════════════════════════

def test_movers_two_period_aggregation(mock_supabase):
    mock_supabase.tables = {
        "transactions": [
            _tx(direction="expense", amount=100.0, occurred_at="2026-04-05T00:00:00+00", primary_tag="food"),
            _tx(direction="expense", amount=130.0, occurred_at="2026-05-08T00:00:00+00", primary_tag="food"),
        ],
        "fx_rates": [],
    }
    out = FinanceService(None).category_movers_via_rest(HID, "2026-05", "2026-05", "2026-04", "2026-04")
    food = next(m for m in out["movers"] if m["tag"] == "food")
    assert food["current_rub"] == 130.0
    assert food["prior_rub"] == 100.0
    assert food["delta_rub"] == 30.0
    assert food["delta_pct"] == 30


def test_movers_new_category_delta_pct_null(mock_supabase):
    mock_supabase.tables = {
        "transactions": [
            _tx(direction="expense", amount=50.0, occurred_at="2026-05-08T00:00:00+00", primary_tag="newthing"),
        ],
        "fx_rates": [],
    }
    out = FinanceService(None).category_movers_via_rest(HID, "2026-05", "2026-05", "2026-04", "2026-04")
    row = next(m for m in out["movers"] if m["tag"] == "newthing")
    assert row["prior_rub"] == 0.0
    assert row["delta_pct"] is None


def test_movers_sorted_by_abs_delta(mock_supabase):
    mock_supabase.tables = {
        "transactions": [
            # food: +30 (small)
            _tx(direction="expense", amount=100.0, occurred_at="2026-04-05T00:00:00+00", primary_tag="food"),
            _tx(direction="expense", amount=130.0, occurred_at="2026-05-05T00:00:00+00", primary_tag="food"),
            # rent: -500 (large negative)
            _tx(direction="expense", amount=2000.0, occurred_at="2026-04-15T00:00:00+00", primary_tag="rent"),
            _tx(direction="expense", amount=1500.0, occurred_at="2026-05-15T00:00:00+00", primary_tag="rent"),
        ],
        "fx_rates": [],
    }
    out = FinanceService(None).category_movers_via_rest(HID, "2026-05", "2026-05", "2026-04", "2026-04")
    tags = [m["tag"] for m in out["movers"]]
    assert tags[0] == "rent"  # |delta|=500
    assert tags[1] == "food"  # |delta|=30
