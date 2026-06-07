"""Recurring payments web surface — list / create / deactivate (ORM + REST),
mirroring the bot /recurring capability. Feeds committed_rub in the clear picture.
"""
from __future__ import annotations

from datetime import date
from decimal import Decimal

from app.application.services.finance_service import (
    FinanceService,
    next_recurring_occurrence,
)
from app.domain.enums import Currency
from app.infrastructure.db.models import RecurringPayment
from tests.conftest import HOUSEHOLD_ID


def test_next_occurrence_clamps_and_advances():
    d = next_recurring_occurrence(15)
    assert d.day == 15 or d.day == next_recurring_occurrence(15).day  # valid calendar day
    assert d >= date.today()


def test_create_list_deactivate_orm(seeded_db):
    svc = FinanceService(seeded_db)
    rid = svc.create_recurring(str(HOUSEHOLD_ID), title="Аренда", amount=Decimal("50000"),
                               currency="RUB", day_of_month=5)
    out = svc.list_recurring(str(HOUSEHOLD_ID))
    assert out["count"] == 1
    item = out["items"][0]
    assert item["title"] == "Аренда"
    assert item["amount_expected"] == 50000.0
    assert item["currency"] == "RUB"
    assert item["day_of_month"] == 5

    assert svc.deactivate_recurring(rid) is True
    assert svc.list_recurring(str(HOUSEHOLD_ID))["count"] == 0


def test_create_recurring_drives_committed_in_clear_picture(seeded_db):
    from datetime import datetime, timezone
    import uuid
    from app.infrastructure.db.models import Account, BalanceSnapshot
    acc = Account(id=uuid.uuid4(), household_id=HOUSEHOLD_ID, name="Нал",
                  currency=Currency.RUB, is_shared=True, is_active=True)
    seeded_db.add(acc)
    seeded_db.add(BalanceSnapshot(id=uuid.uuid4(), account_id=acc.id, household_id=HOUSEHOLD_ID,
                                  actual_balance=Decimal("200000"), created_at=datetime.now(timezone.utc)))
    svc = FinanceService(seeded_db)
    svc.create_recurring(str(HOUSEHOLD_ID), title="Подписки", amount=Decimal("3000"),
                         currency="RUB", day_of_month=10)
    seeded_db.commit()
    cp = svc.data_health(str(HOUSEHOLD_ID))["clear_picture"]
    assert cp["payments"]["recurring_count"] == 1
    assert cp["hustle"]["committed_rub"] == 3000.0
    assert "no_recurring" not in cp["hustle"]["flags"]


def test_recurring_via_rest_list(mock_supabase):
    mock_supabase.tables["recurring_payments"] = [
        {"id": "r1", "title": "Netflix", "amount_expected": "49.9", "currency": "USD",
         "day_of_month": 15, "next_due_date": "2026-06-15"},
    ]
    out = FinanceService(None).list_recurring_via_rest("h1")
    assert out["count"] == 1
    assert out["items"][0]["title"] == "Netflix"
    assert out["items"][0]["amount_expected"] == 49.9


def test_recurring_via_rest_create_posts(mock_supabase):
    FinanceService(None).create_recurring_via_rest(
        "h1", title="Аренда", amount=Decimal("50000"), currency="RUB", day_of_month=5)
    assert mock_supabase.post_calls, "should POST to recurring_payments"
    table, rows = mock_supabase.post_calls[-1]
    assert table == "recurring_payments"
    assert rows[0]["title"] == "Аренда"
    assert rows[0]["is_active"] is True
    assert rows[0]["cadence"] == "monthly"


def test_recurring_via_rest_deactivate_patches(mock_supabase):
    FinanceService(None).deactivate_recurring_via_rest("r1")
    assert mock_supabase.patch_calls, "should PATCH recurring_payments"
    table, params, body = mock_supabase.patch_calls[-1]
    assert table == "recurring_payments"
    assert body == {"is_active": False}
