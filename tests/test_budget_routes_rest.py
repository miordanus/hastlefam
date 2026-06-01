"""Route tests proving the budgets endpoints no longer 500 on the REST-only
host (Round 2). They must hit the REST path, never SQLAlchemy/get_db.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

import app.main as app_main
from tests.conftest import HOUSEHOLD_ID

client = TestClient(app_main.app)
client.cookies.set("hf_session", "x")


class FakeSB:
    tables: dict = {}
    posts: list = []
    patches: list = []

    def __init__(self, *a, **k):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def get(self, table, params=None):
        return list(FakeSB.tables.get(table, []))

    def post(self, table, rows):
        FakeSB.posts.append((table, rows))
        FakeSB.tables.setdefault(table, []).extend(rows)
        return rows

    def patch(self, table, params, body):
        FakeSB.patches.append((table, params, body))
        return [body]


@pytest.fixture()
def rest(monkeypatch):
    monkeypatch.setattr(app_main, "verify_session", lambda t: {"uid": "u", "hid": str(HOUSEHOLD_ID)})
    monkeypatch.setattr("app.api.routers.finance._use_rest", lambda: True)
    monkeypatch.setattr("app.infrastructure.supabase.SupabaseClient", FakeSB)
    FakeSB.tables = {}
    FakeSB.posts = []
    FakeSB.patches = []


def test_list_budgets_rest_returns_status(rest):
    FakeSB.tables["tag_budgets"] = [{
        "id": "b1", "tag": "еда", "limit_amount": "15000", "rollover_amount": "0",
        "rollover_enabled": False, "currency": "RUB", "month_key": "2026-05",
    }]
    FakeSB.tables["transactions"] = [{
        "primary_tag": "еда", "amount": "12000", "direction": "expense",
        "is_planned": False, "is_skipped": False, "occurred_at": "2026-05-10T00:00:00+00:00",
    }]
    resp = client.get(f"/finance/budgets?household_id={HOUSEHOLD_ID}&month=2026-05")
    assert resp.status_code == 200      # was 500 on the REST-only host
    b = resp.json()["budgets"][0]
    assert b["tag"] == "еда"
    assert b["status"] == "at_risk"


def test_upsert_budget_rest_creates_when_absent(rest):
    FakeSB.tables["tag_budgets"] = []   # none exists → POST
    resp = client.post("/finance/budgets", json={
        "household_id": str(HOUSEHOLD_ID), "month_key": "2026-05",
        "tag": "#Еда", "limit_amount": "15000",
    })
    assert resp.status_code == 200
    assert resp.json()["tag"] == "еда"
    assert len(FakeSB.posts) == 1 and FakeSB.posts[0][0] == "tag_budgets"
    assert FakeSB.posts[0][1][0]["tag"] == "еда"


def test_upsert_budget_rest_patches_when_present(rest):
    FakeSB.tables["tag_budgets"] = [{"id": "b1"}]   # exists → PATCH
    resp = client.post("/finance/budgets", json={
        "household_id": str(HOUSEHOLD_ID), "month_key": "2026-05",
        "tag": "еда", "limit_amount": "20000",
    })
    assert resp.status_code == 200
    assert len(FakeSB.patches) == 1
    table, params, body = FakeSB.patches[0]
    assert table == "tag_budgets"
    assert params == {"id": "eq.b1"}
    assert body["limit_amount"] == pytest.approx(20000)
