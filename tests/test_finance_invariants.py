"""Cross-method invariants of the finance REST aggregations.

These tests don't just hit a single method — they assert that the methods
are internally consistent with each other. Catches drift between
implementations that the per-method tests in test_finance_via_rest.py can
miss.
"""
from datetime import date
from unittest.mock import patch

import pytest

from app.application.services.finance_service import FinanceService

# Reuse helpers + constants from the via_rest test module
from tests.test_finance_via_rest import (
    HID, ACC_RUB, ACC_USDT,
    _account, _snap, _tx, _fx, _freeze_today,
)


def test_balance_eq_start_plus_actual_delta(mock_supabase):
    """ЗАКОН: balance_value_rub == start_balance_rub + (actual income - actual expense)."""
    mock_supabase.tables = {
        "accounts": [_account(ACC_RUB, "RUB")],
        "transactions": [
            _tx(direction="income",  amount=300.0, occurred_at="2026-05-05T00:00:00+00"),
            _tx(direction="expense", amount=200.0, occurred_at="2026-05-10T00:00:00+00"),
            _tx(direction="expense", amount=400.0, occurred_at="2026-05-30T00:00:00+00", is_planned=True),  # planned future, ignored
            _tx(direction="income",  amount=999.0, occurred_at="2026-05-08T00:00:00+00", is_internal_transfer=True),
        ],
        "balance_snapshots": [_snap(ACC_RUB, 1000.0, "2026-05-01T00:00:00+00")],
        "fx_rates": [],
    }
    with _freeze_today(date(2026, 5, 24)):
        out = FinanceService(None).monthly_report_via_rest(HID, 2026, 5)
    assert out["start_balance_rub"] == 1000.0
    assert out["balance_value_rub"] == 1000.0 + 300.0 - 200.0  # = 1100


def test_monthly_totals_matches_monthly_report_actual_delta(mock_supabase):
    """For a single month, monthly_totals.actual_income - actual_expense
    must equal the delta_rub embedded in monthly_report (balance - start).
    """
    txs = [
        _tx(direction="income",  amount=300.0, occurred_at="2026-04-05T00:00:00+00"),
        _tx(direction="expense", amount=120.0, occurred_at="2026-04-10T00:00:00+00"),
        _tx(direction="expense", amount=50.0,  occurred_at="2026-04-12T00:00:00+00"),
    ]
    mock_supabase.tables = {
        "accounts": [_account(ACC_RUB, "RUB")],
        "transactions": txs,
        "balance_snapshots": [_snap(ACC_RUB, 500.0, "2026-04-01T00:00:00+00")],
        "fx_rates": [],
    }
    with _freeze_today(date(2026, 5, 24)):
        report = FinanceService(None).monthly_report_via_rest(HID, 2026, 4)
    delta_from_report = report["balance_value_rub"] - report["start_balance_rub"]

    # Reset the table list for the totals call (mock returns these without filtering)
    mock_supabase.tables["transactions"] = txs
    totals = FinanceService(None).monthly_totals_via_rest(HID, "2026-04", "2026-04")
    delta_from_totals = totals[0]["actual_income_rub"] - totals[0]["actual_expense_rub"]

    assert delta_from_report == delta_from_totals == 130.0


def test_per_date_fx_consistency_across_methods(mock_supabase):
    """A USDT income on a specific date converts to the same RUB amount whether
    queried via monthly_report_via_rest or monthly_totals_via_rest.
    """
    common_tx = _tx(direction="income", amount=10.0, currency="USDT", occurred_at="2026-04-12T00:00:00+00")
    common_fx = [
        _fx("USD", "2026-04-12", 76.0),
        _fx("USD", "2026-05-20", 70.0),  # later rate, must NOT be used
    ]

    mock_supabase.tables = {
        "accounts": [_account(ACC_USDT, "USDT")],
        "transactions": [common_tx],
        "balance_snapshots": [_snap(ACC_USDT, 0.0, "2026-04-01T00:00:00+00")],
        "fx_rates": common_fx,
    }
    with _freeze_today(date(2026, 5, 24)):
        rep = FinanceService(None).monthly_report_via_rest(HID, 2026, 4)
    tot = FinanceService(None).monthly_totals_via_rest(HID, "2026-04", "2026-04")
    assert rep["balance_value_rub"] == 760.0
    assert tot[0]["actual_income_rub"] == 760.0


@pytest.mark.xfail(strict=True, reason="Bug #1 — per-account balance_rub not yet on backend; fixed in follow-up commit")
def test_account_balance_sum_eq_hero_when_no_mid_month_activity(mock_supabase):
    """When each account's latest snapshot dates BEFORE month-start and there
    are no in-month txs, the sum of per-account balance_rub (backend-supplied)
    must equal balance_value_rub. Locks the Bug #1 reconciliation invariant.
    """
    mock_supabase.tables = {
        "accounts": [_account(ACC_RUB, "RUB", "Cash"), _account(ACC_USDT, "USDT", "USDT")],
        "transactions": [],
        "balance_snapshots": [
            _snap(ACC_RUB, 500.0, "2026-04-15T00:00:00+00"),
            _snap(ACC_USDT, 10.0, "2026-04-15T00:00:00+00"),
        ],
        "fx_rates": [_fx("USD", "2026-04-15", 80.0), _fx("USD", "2026-05-20", 70.0)],
    }
    with _freeze_today(date(2026, 5, 24)):
        out = FinanceService(None).monthly_report_via_rest(HID, 2026, 5)

    # After Bug #1 fix, each account entry should carry balance_rub.
    sum_cards = sum((a.get("balance_rub") or 0.0) for a in out["accounts"])
    assert sum_cards == out["balance_value_rub"]
    # And specifically the USDT card converts at the snapshot's own date rate.
    usdt_card = next(a for a in out["accounts"] if a["currency"] == "USDT")
    assert usdt_card["balance_rub"] == 800.0  # 10 USDT × 80 (snap-date rate)
