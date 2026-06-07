"""Clear-picture / hustle (safety-floor runway) block on the data-health page.

Covers the pure _clear_picture() math + confidence flags, and that both
data_health() (ORM) and data_health_via_rest() (REST) embed a `clear_picture`
block. The hustle metric answers "how much must I earn to keep liquid above a
floor for N months", and flags when the answer is a guess (no recurring set up,
income stale, balances stale).
"""
from __future__ import annotations

import uuid
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

from app.application.services.finance_service import FinanceService, _clear_picture
from app.domain.enums import Currency, TransactionDirection
from app.infrastructure.db.models import (
    Account,
    BalanceSnapshot,
    RecurringPayment,
    Transaction,
)
from tests.conftest import ACCOUNT_ID, HOUSEHOLD_ID, USER_ID


# ─── Pure _clear_picture() ────────────────────────────────────────────────────

def _cp(**over):
    base = dict(
        liquid_rub=300_000.0, avg_burn_rub=20_000.0, expected_income_rub=10_000.0,
        committed_rub=10_000.0, recurring_count=1, income_age_days=5,
        balance_status="green", overdue_rub=0.0, overdue_count=0,
        upcoming_planned_count=0, untagged_count=0,
    )
    base.update(over)
    return _clear_picture(**base)


def test_hustle_gap_when_income_below_need():
    # liquid sits exactly on the floor, so the whole burn must come from income.
    cp = _cp(liquid_rub=100_000.0, avg_burn_rub=50_000.0, committed_rub=0.0,
             expected_income_rub=10_000.0, recurring_count=1)
    h = cp["hustle"]
    assert h["needed_per_month_rub"] == 50_000.0
    assert h["gap_rub"] == 40_000.0          # 50k needed − 10k earned
    assert h["runway_months"] == 0.0         # already at the floor


def test_runway_none_when_income_covers_burn():
    cp = _cp(liquid_rub=500_000.0, avg_burn_rub=20_000.0, committed_rub=0.0,
             expected_income_rub=50_000.0)
    h = cp["hustle"]
    assert h["runway_months"] is None        # not drawing down
    assert h["gap_rub"] == 0.0


def test_runway_months_positive():
    cp = _cp(liquid_rub=300_000.0, avg_burn_rub=40_000.0, committed_rub=0.0,
             expected_income_rub=0.0)
    # (300k − 100k floor) / 40k net burn = 5.0 months
    assert cp["hustle"]["runway_months"] == 5.0


def test_confidence_green_when_data_complete():
    assert _cp()["hustle"]["confidence"] == "green"


def test_confidence_amber_on_single_gap():
    assert _cp(recurring_count=0)["hustle"]["confidence"] == "amber"
    assert "no_recurring" in _cp(recurring_count=0)["hustle"]["flags"]


def test_confidence_red_on_multiple_gaps():
    h = _cp(recurring_count=0, income_age_days=60, balance_status="red")["hustle"]
    assert h["confidence"] == "red"
    assert set(h["flags"]) == {"no_recurring", "income_stale", "stale_balance"}


def test_income_stale_when_no_income_ever():
    assert "income_stale" in _cp(income_age_days=None)["hustle"]["flags"]


def test_payments_status_red_without_recurring():
    assert _cp(recurring_count=0)["payments"]["status"] == "red"


# ─── data_health() ORM integration ────────────────────────────────────────────

def _rub_account(db, name="Нал"):
    acc = Account(id=uuid.uuid4(), household_id=HOUSEHOLD_ID, name=name,
                  currency=Currency.RUB, is_shared=True, is_active=True)
    db.add(acc)
    return acc


def _snap(db, account_id, amount, days_ago=0):
    when = datetime.now(timezone.utc) - timedelta(days=days_ago)
    db.add(BalanceSnapshot(id=uuid.uuid4(), account_id=account_id, household_id=HOUSEHOLD_ID,
                           actual_balance=Decimal(str(amount)), created_at=when))


def _txn(db, direction, amount, days_ago):
    db.add(Transaction(
        id=uuid.uuid4(), household_id=HOUSEHOLD_ID, user_id=USER_ID, direction=direction,
        amount=Decimal(str(amount)), currency=Currency.RUB,
        occurred_at=datetime.now(timezone.utc) - timedelta(days=days_ago),
        merchant_raw="x", source="test", parse_status="ok", extra_tags=[],
        primary_tag="еда", is_planned=False, is_internal_transfer=False, is_skipped=False))


def test_data_health_embeds_clear_picture(seeded_db):
    acc = _rub_account(seeded_db)
    _snap(seeded_db, acc.id, 300_000, days_ago=0)
    _snap(seeded_db, ACCOUNT_ID, 0, days_ago=0)  # seeded USD account — keep it "fresh" too
    _txn(seeded_db, TransactionDirection.EXPENSE, 60_000, days_ago=10)  # burn 60k/3 = 20k
    _txn(seeded_db, TransactionDirection.INCOME, 30_000, days_ago=5)    # income 30k/3 = 10k
    seeded_db.add(RecurringPayment(
        id=uuid.uuid4(), household_id=HOUSEHOLD_ID, title="Аренда",
        amount_expected=Decimal("10000"), currency=Currency.RUB,
        cadence="monthly", next_due_date=date.today(), is_active=True))
    seeded_db.commit()

    out = FinanceService(seeded_db).data_health(str(HOUSEHOLD_ID))
    cp = out["clear_picture"]
    assert cp["balance_rub"] == 300_000.0
    assert cp["payments"]["recurring_count"] == 1
    h = cp["hustle"]
    assert h["avg_burn_rub"] == 20_000.0
    assert h["expected_income_rub"] == 10_000.0
    assert h["committed_rub"] == 10_000.0
    # net burn = 20k + 10k − 10k = 20k → (300k − 100k)/20k = 10 months
    assert h["runway_months"] == 10.0
    assert h["confidence"] == "green"


def test_data_health_clear_picture_flags_guesswork(seeded_db):
    # Stale balance, no recurring, no income → the hustle answer is a guess.
    acc = _rub_account(seeded_db)
    _snap(seeded_db, acc.id, 120_000, days_ago=40)  # ≥14d → red balance
    _txn(seeded_db, TransactionDirection.EXPENSE, 90_000, days_ago=20)
    seeded_db.commit()

    out = FinanceService(seeded_db).data_health(str(HOUSEHOLD_ID))
    h = out["clear_picture"]["hustle"]
    assert h["confidence"] == "red"
    assert "no_recurring" in h["flags"]
    assert "income_stale" in h["flags"]
    assert "stale_balance" in h["flags"]


# ─── data_health_via_rest() integration ───────────────────────────────────────

def test_data_health_via_rest_embeds_clear_picture(mock_supabase):
    A = "11111111-1111-1111-1111-111111111111"
    now = datetime.now(timezone.utc)
    mock_supabase.tables["users"] = [{"id": "u1", "name": "Max"}]
    mock_supabase.tables["accounts"] = [
        {"id": A, "name": "Нал", "currency": "RUB", "owner_user_id": "u1"}
    ]
    mock_supabase.tables["balance_snapshots"] = [
        {"account_id": A, "actual_balance": "300000", "created_at": now.isoformat()},
    ]
    mock_supabase.tables["transactions"] = [
        {"id": "t1", "account_id": A, "occurred_at": (now - timedelta(days=10)).isoformat(),
         "created_at": (now - timedelta(days=10)).isoformat(), "amount": "60000",
         "currency": "RUB", "direction": "expense", "is_planned": False,
         "is_internal_transfer": False, "is_skipped": False, "primary_tag": "еда",
         "merchant_raw": "shop", "user_id": "u1"},
    ]
    mock_supabase.tables["recurring_payments"] = [
        {"amount_expected": "10000", "currency": "RUB", "is_active": True},
    ]
    mock_supabase.tables["raw_import_transactions"] = []

    out = FinanceService(None).data_health_via_rest("h1", "u1")
    cp = out["clear_picture"]
    assert cp["balance_rub"] == 300_000.0
    assert cp["payments"]["recurring_count"] == 1
    assert cp["hustle"]["avg_burn_rub"] == 20_000.0
    assert cp["hustle"]["committed_rub"] == 10_000.0
