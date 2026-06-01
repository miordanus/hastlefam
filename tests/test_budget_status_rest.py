"""REST mirror of get_budget_status (Round 2 — fixes the dashboard budgets 500).

The live web is REST-only; get_budget_status (SQLAlchemy) 500s there. The
*_via_rest sibling must produce the same per-tag status from PostgREST data.
The stub SupabaseClient ignores filters, so we preload exactly the rows a query
should see and the function applies the ЗАКОН filters in Python.
"""
from __future__ import annotations

from decimal import Decimal

from app.application.services.budget_service import get_budget_status_via_rest


def _tx(tag, amount, *, direction="expense", is_planned=False, is_skipped=False,
        occurred_at="2026-05-10T00:00:00+00:00"):
    return {"primary_tag": tag, "amount": str(amount), "direction": direction,
            "is_planned": is_planned, "is_skipped": is_skipped,
            "is_internal_transfer": False, "occurred_at": occurred_at}


def _budget(tag, limit, *, rollover="0", rollover_enabled=False, currency="RUB"):
    return {"id": f"b-{tag}", "tag": tag, "limit_amount": str(limit),
            "rollover_amount": str(rollover), "rollover_enabled": rollover_enabled,
            "currency": currency, "month_key": "2026-05", "household_id": "h1"}


def test_actual_spent_and_at_risk_status(mock_supabase):
    mock_supabase.tables["tag_budgets"] = [_budget("еда", 15000)]
    mock_supabase.tables["transactions"] = [_tx("еда", 7000), _tx("еда", 5000)]
    out = get_budget_status_via_rest("h1", "2026-05")
    b = next(x for x in out if x["tag"] == "еда")
    assert b["actual_spent"] == Decimal("12000")
    assert b["effective_limit"] == Decimal("15000")
    assert b["pct_used"] == 80.0
    assert b["status"] == "at_risk"
    assert b["currency"] == "RUB"


def test_over_budget_status(mock_supabase):
    mock_supabase.tables["tag_budgets"] = [_budget("такси", 1000)]
    mock_supabase.tables["transactions"] = [_tx("такси", 1200)]
    out = get_budget_status_via_rest("h1", "2026-05")
    assert out[0]["status"] == "over_budget"


def test_effective_limit_includes_stored_rollover(mock_supabase):
    mock_supabase.tables["tag_budgets"] = [_budget("еда", 10000, rollover="5000")]
    mock_supabase.tables["transactions"] = [_tx("еда", 12000)]
    out = get_budget_status_via_rest("h1", "2026-05")
    assert out[0]["effective_limit"] == Decimal("15000")
    assert out[0]["status"] == "at_risk"      # 12000 / 15000 = 80%


def test_excludes_planned_skipped_other_tag_and_income(mock_supabase):
    mock_supabase.tables["tag_budgets"] = [_budget("еда", 10000)]
    mock_supabase.tables["transactions"] = [
        _tx("еда", 1000),                          # counts
        _tx("еда", 9999, is_planned=True),         # planned (past month) — not actual
        _tx("еда", 500, is_skipped=True),          # skipped
        _tx("еда", 700, direction="income"),       # income
        _tx("такси", 800),                         # other tag
    ]
    out = get_budget_status_via_rest("h1", "2026-05")
    assert out[0]["actual_spent"] == Decimal("1000")
