"""Route-wiring tests for the web write endpoints (Task 2).

Auth-gated routes: set a session cookie + monkeypatch verify_session (mirrors
test_data_health.py). DB logic is covered by test_finance_writes.py at the
service layer; here we monkeypatch the service so the route is exercised
without a real DB (TestClient runs sync endpoints in a worker thread, which
can't share the in-memory SQLite connection).
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


@pytest.fixture()
def authed(monkeypatch):
    monkeypatch.setattr(app_main, "verify_session", lambda t: {"uid": "u", "hid": str(HOUSEHOLD_ID)})
    monkeypatch.setattr("app.api.routers.finance._use_rest", lambda: False)


class _FakeTx:
    def __init__(self, tag="еда"):
        self.id = uuid.uuid4()
        self.tag = tag
        self.limit_amount = 15000


# ─── SQLAlchemy path (service monkeypatched) ─────────────────────────────────

def test_create_transaction_route(authed, monkeypatch):
    captured = {}

    def fake_create(self, **kw):
        captured.update(kw)
        return _FakeTx()

    monkeypatch.setattr(FinanceService, "create_transaction", fake_create)
    resp = client.post("/finance/transactions", json={
        "household_id": str(HOUSEHOLD_ID), "amount": "500", "currency": "RUB",
        "direction": "expense", "occurred_at": "2026-05-10", "primary_tag": "#Еда",
        "account_id": str(ACCOUNT_ID), "merchant": "Пятёрочка",
    })
    assert resp.status_code == 200
    assert resp.json()["ok"] is True
    assert captured["amount"] == pytest.approx(500)
    assert captured["primary_tag"] == "#Еда"      # route passes raw; service normalizes


def test_create_transaction_validation_error(authed):
    resp = client.post("/finance/transactions", json={
        "household_id": str(HOUSEHOLD_ID), "currency": "RUB",
        "direction": "expense", "occurred_at": "2026-05-10",
    })
    assert resp.status_code == 422


def test_edit_transaction_route(authed, monkeypatch):
    captured = {}

    def fake_update(self, tx_id, **fields):
        captured["tx_id"] = tx_id
        captured.update(fields)
        return _FakeTx()

    monkeypatch.setattr(FinanceService, "update_transaction", fake_update)
    tid = str(uuid.uuid4())
    resp = client.post(f"/finance/transactions/{tid}/edit", json={
        "amount": "250", "primary_tag": "новое", "currency": "USD",
    })
    assert resp.status_code == 200
    assert captured["tx_id"] == tid
    assert captured["currency"] == "USD"
    assert "direction" not in captured            # exclude_unset → omitted field not passed


def test_edit_transaction_missing_404(authed, monkeypatch):
    monkeypatch.setattr(FinanceService, "update_transaction", lambda self, tx_id, **f: None)
    resp = client.post(f"/finance/transactions/{uuid.uuid4()}/edit", json={"amount": "5"})
    assert resp.status_code == 404


def test_upsert_budget_route(authed, monkeypatch):
    monkeypatch.setattr(FinanceService, "upsert_tag_budget",
                        lambda self, *a, **k: _FakeTx(tag="еда"))
    resp = client.post("/finance/budgets", json={
        "household_id": str(HOUSEHOLD_ID), "month_key": "2026-05",
        "tag": "#Еда", "limit_amount": "15000",
    })
    assert resp.status_code == 200
    assert resp.json()["tag"] == "еда"


def test_list_budgets_route(authed, monkeypatch):
    monkeypatch.setattr("app.application.services.budget_service.get_budget_status",
                        lambda hid, month, db: [{"tag": "еда", "limit_amount": 15000}])
    resp = client.get(f"/finance/budgets?household_id={HOUSEHOLD_ID}&month=2026-05")
    assert resp.status_code == 200
    assert [b["tag"] for b in resp.json()["budgets"]] == ["еда"]


# ─── REST path (fake Supabase client) ────────────────────────────────────────

class _FakeSB:
    posts: list = []
    patches: list = []

    def __init__(self, *a, **k):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def post(self, table, rows):
        _FakeSB.posts.append((table, rows))
        return rows

    def patch(self, table, params, body):
        _FakeSB.patches.append((table, params, body))
        return [body]


def test_create_transaction_rest_path(monkeypatch):
    monkeypatch.setattr(app_main, "verify_session", lambda t: {"uid": "u", "hid": str(HOUSEHOLD_ID)})
    monkeypatch.setattr("app.api.routers.finance._use_rest", lambda: True)
    monkeypatch.setattr("app.infrastructure.supabase.SupabaseClient", _FakeSB)
    _FakeSB.posts.clear()
    resp = client.post("/finance/transactions", json={
        "household_id": str(HOUSEHOLD_ID), "amount": "500", "currency": "RUB",
        "direction": "expense", "occurred_at": "2026-05-10", "primary_tag": "#Еда",
    })
    assert resp.status_code == 200
    assert len(_FakeSB.posts) == 1
    table, rows = _FakeSB.posts[0]
    assert table == "transactions"
    assert rows[0]["source"] == "web"
    assert rows[0]["primary_tag"] == "еда"
    assert rows[0]["currency"] == "RUB"
    assert len(rows[0]["dedup_fingerprint"]) == 64


def test_edit_transaction_rest_path(monkeypatch):
    monkeypatch.setattr(app_main, "verify_session", lambda t: {"uid": "u", "hid": str(HOUSEHOLD_ID)})
    monkeypatch.setattr("app.api.routers.finance._use_rest", lambda: True)
    monkeypatch.setattr("app.infrastructure.supabase.SupabaseClient", _FakeSB)
    _FakeSB.patches.clear()
    tid = str(uuid.uuid4())
    resp = client.post(f"/finance/transactions/{tid}/edit", json={"amount": "250", "primary_tag": "#Еда"})
    assert resp.status_code == 200
    assert len(_FakeSB.patches) == 1
    table, params, body = _FakeSB.patches[0]
    assert table == "transactions"
    assert params == {"id": f"eq.{tid}"}
    assert body["amount"] == pytest.approx(250)
    assert body["primary_tag"] == "еда"
