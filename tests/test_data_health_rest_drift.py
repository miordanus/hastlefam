"""Reconciliation drift via the REST variant of data_health (Tasks 1 & 4).

Mirrors test_reconciliation_drift.py for data_health_via_rest(). The stub
SupabaseClient ignores PostgREST filters, so drift assertions rely on the
service applying account/window/invariant filtering in Python.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from app.application.services.finance_service import FinanceService

A = "11111111-1111-1111-1111-111111111111"


def _now():
    return datetime.now(timezone.utc)


def _iso(days_ago):
    return (_now() - timedelta(days=days_ago)).isoformat()


def _base_tables(mock_supabase):
    mock_supabase.tables["users"] = [{"id": "u1", "name": "Max"}]
    mock_supabase.tables["accounts"] = [
        {"id": A, "name": "Карта", "currency": "RUB", "owner_user_id": "u1"}
    ]
    mock_supabase.tables["raw_import_transactions"] = []


def _snaps_two(mock_supabase):
    # Ordered created_at desc (latest first), as PostgREST would return.
    mock_supabase.tables["balance_snapshots"] = [
        {"account_id": A, "actual_balance": "800", "created_at": _iso(2)},
        {"account_id": A, "actual_balance": "1000", "created_at": _iso(10)},
    ]


def test_rest_drift_explained_by_attributed_expense(mock_supabase):
    _base_tables(mock_supabase)
    _snaps_two(mock_supabase)
    mock_supabase.tables["transactions"] = [{
        "id": "t1", "account_id": A, "occurred_at": _iso(5), "created_at": _iso(5),
        "amount": "200", "currency": "RUB", "direction": "expense",
        "is_planned": False, "is_internal_transfer": False, "is_skipped": False,
        "primary_tag": "еда", "merchant_raw": "shop", "user_id": "u1",
    }]
    out = FinanceService(None).data_health_via_rest("h1", "u1")
    e = next(a for a in out["balances"]["accounts"] if a["account_id"] == A)
    assert e["computed_balance"] == 800.0
    assert e["drift"] == 0.0
    assert e["drift_status"] == "green"


def test_rest_drift_unexplained_is_amber_and_routed(mock_supabase):
    _base_tables(mock_supabase)
    _snaps_two(mock_supabase)
    mock_supabase.tables["transactions"] = []
    out = FinanceService(None).data_health_via_rest("h1", "u1")
    e = next(a for a in out["balances"]["accounts"] if a["account_id"] == A)
    assert e["computed_balance"] == 1000.0
    assert e["drift"] == -200.0
    assert e["drift_status"] == "amber"
    me = next(p for p in out["people"] if p["is_you"])
    assert any(t["kind"] == "drift" and "Карта" in t["label"] for t in me["todos"])


def test_rest_drift_none_with_single_snapshot(mock_supabase):
    _base_tables(mock_supabase)
    mock_supabase.tables["balance_snapshots"] = [
        {"account_id": A, "actual_balance": "800", "created_at": _iso(2)},
    ]
    mock_supabase.tables["transactions"] = []
    out = FinanceService(None).data_health_via_rest("h1", "u1")
    e = next(a for a in out["balances"]["accounts"] if a["account_id"] == A)
    assert e["computed_balance"] is None
    assert e["drift"] is None
    assert e["drift_status"] == "green"
