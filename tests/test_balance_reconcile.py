"""POST /finance/balances — record a balance snapshot from the web (Round 2).

This is the web equivalent of the bot's 🔄 Сверить. REST path writes a
balance_snapshots row; SQLAlchemy path reuses update_balance_snapshot.
"""
from __future__ import annotations

import uuid

import pytest
from fastapi.testclient import TestClient

import app.main as app_main
from app.application.services.finance_service import FinanceService
from tests.conftest import ACCOUNT_ID, HOUSEHOLD_ID

client = TestClient(app_main.app)
client.cookies.set("hf_session", "x")


class FakeSB:
    posts: list = []

    def __init__(self, *a, **k):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def post(self, table, rows):
        FakeSB.posts.append((table, rows))
        return rows


def test_record_balance_rest_path(monkeypatch):
    monkeypatch.setattr(app_main, "verify_session", lambda t: {"uid": "11111111-1111-1111-1111-111111111111", "hid": str(HOUSEHOLD_ID)})
    monkeypatch.setattr("app.api.routers.finance._use_rest", lambda: True)
    monkeypatch.setattr("app.infrastructure.supabase.SupabaseClient", FakeSB)
    FakeSB.posts = []
    resp = client.post("/finance/balances", json={
        "household_id": str(HOUSEHOLD_ID), "account_id": str(ACCOUNT_ID), "actual_balance": "12345.67",
    })
    assert resp.status_code == 200
    assert resp.json()["ok"] is True
    assert len(FakeSB.posts) == 1
    table, rows = FakeSB.posts[0]
    assert table == "balance_snapshots"
    row = rows[0]
    assert row["account_id"] == str(ACCOUNT_ID)
    assert row["household_id"] == str(HOUSEHOLD_ID)
    assert float(row["actual_balance"]) == pytest.approx(12345.67)
    assert row["created_by_user_id"] == "11111111-1111-1111-1111-111111111111"
    assert row["created_at"]            # ISO timestamp present


def test_record_balance_sqlalchemy_path(monkeypatch):
    monkeypatch.setattr(app_main, "verify_session", lambda t: {"uid": "u", "hid": str(HOUSEHOLD_ID)})
    monkeypatch.setattr("app.api.routers.finance._use_rest", lambda: False)

    captured = {}

    class _Snap:
        id = uuid.uuid4()

    def fake_update(self, account_id, household_id, new_balance, user_id=None):
        captured.update(account_id=account_id, household_id=household_id, new_balance=new_balance)
        return _Snap(), None

    monkeypatch.setattr(FinanceService, "update_balance_snapshot", fake_update)
    resp = client.post("/finance/balances", json={
        "household_id": str(HOUSEHOLD_ID), "account_id": str(ACCOUNT_ID), "actual_balance": "5000",
    })
    assert resp.status_code == 200
    assert resp.json()["snapshot_id"] == str(_Snap.id)
    assert captured["account_id"] == str(ACCOUNT_ID)
    assert float(captured["new_balance"]) == pytest.approx(5000)
