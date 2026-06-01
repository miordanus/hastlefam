"""Tests for reconciliation drift in data_health (Tasks 1 & 4).

Drift = reported balance (latest snapshot) − computed balance (prior snapshot +
attributed real transactions in the window). Derived on the fly, so a
past-dated expense added later automatically shrinks the drift.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from app.application.services.finance_service import FinanceService
from app.domain.enums import Currency, TransactionDirection
from app.infrastructure.db.models import Account, BalanceSnapshot, Transaction
from tests.conftest import HOUSEHOLD_ID, USER_ID


def _now():
    return datetime.now(timezone.utc)


def _account(db, name="Acct", owner_user_id=None):
    acc = Account(id=uuid.uuid4(), household_id=HOUSEHOLD_ID, owner_user_id=owner_user_id,
                  name=name, currency=Currency.RUB, is_active=True)
    db.add(acc)
    db.commit()
    return acc


def _snap(db, account_id, *, days_ago, balance):
    db.add(BalanceSnapshot(id=uuid.uuid4(), account_id=account_id, household_id=HOUSEHOLD_ID,
                           actual_balance=Decimal(str(balance)), created_at=_now() - timedelta(days=days_ago)))
    db.commit()


def _tx(db, account_id, *, amount, days_ago, direction=TransactionDirection.EXPENSE,
        is_planned=False, is_internal_transfer=False, is_skipped=False):
    tx = Transaction(id=uuid.uuid4(), household_id=HOUSEHOLD_ID, account_id=account_id,
                     direction=direction, amount=Decimal(str(amount)), currency=Currency.RUB,
                     occurred_at=_now() - timedelta(days=days_ago), merchant_raw="x", source="test",
                     parse_status="ok", is_planned=is_planned, is_internal_transfer=is_internal_transfer,
                     is_skipped=is_skipped, extra_tags=[])
    db.add(tx)
    db.commit()
    return tx


def _acct_entry(out, account_id):
    return next(a for a in out["balances"]["accounts"] if a["account_id"] == str(account_id))


def test_drift_computed_between_two_snapshots(seeded_db):
    acc = _account(seeded_db, name="Карта")
    _snap(seeded_db, acc.id, days_ago=10, balance=1000)
    _snap(seeded_db, acc.id, days_ago=2, balance=800)   # reported drop of 200, nothing explains it
    out = FinanceService(seeded_db).data_health(str(HOUSEHOLD_ID))
    e = _acct_entry(out, acc.id)
    assert e["computed_balance"] == 1000.0       # prev snapshot + no txns
    assert e["drift"] == -200.0                  # 800 − 1000
    assert e["drift_status"] == "amber"


def test_drift_shrinks_when_past_dated_expense_added(seeded_db):
    acc = _account(seeded_db, name="Карта")
    _snap(seeded_db, acc.id, days_ago=10, balance=1000)
    _snap(seeded_db, acc.id, days_ago=2, balance=800)
    # A forgotten 200 expense, dated inside the window, is added afterwards.
    _tx(seeded_db, acc.id, amount=200, days_ago=5, direction=TransactionDirection.EXPENSE)
    out = FinanceService(seeded_db).data_health(str(HOUSEHOLD_ID))
    e = _acct_entry(out, acc.id)
    assert e["computed_balance"] == 800.0   # 1000 − 200
    assert e["drift"] == 0.0
    assert e["drift_status"] == "green"


def test_drift_none_with_single_snapshot(seeded_db):
    acc = _account(seeded_db, name="Карта")
    _snap(seeded_db, acc.id, days_ago=2, balance=800)
    out = FinanceService(seeded_db).data_health(str(HOUSEHOLD_ID))
    e = _acct_entry(out, acc.id)
    assert e["computed_balance"] is None
    assert e["drift"] is None
    assert e["drift_status"] == "green"  # nothing to reconcile yet


def test_drift_excludes_invariant_and_other_accounts(seeded_db):
    acc = _account(seeded_db, name="Карта")
    other = _account(seeded_db, name="Другой")
    _snap(seeded_db, acc.id, days_ago=10, balance=1000)
    _snap(seeded_db, acc.id, days_ago=2, balance=1000)  # reported unchanged
    # None of these should affect acc's computed balance:
    _tx(seeded_db, acc.id, amount=50, days_ago=5, is_planned=True)
    _tx(seeded_db, acc.id, amount=50, days_ago=5, is_internal_transfer=True)
    _tx(seeded_db, acc.id, amount=50, days_ago=5, is_skipped=True)
    _tx(seeded_db, acc.id, amount=50, days_ago=5, direction=TransactionDirection.EXCHANGE)
    _tx(seeded_db, other.id, amount=50, days_ago=5)   # different account
    _tx(seeded_db, acc.id, amount=50, days_ago=20)    # before the window
    out = FinanceService(seeded_db).data_health(str(HOUSEHOLD_ID))
    e = _acct_entry(out, acc.id)
    assert e["computed_balance"] == 1000.0
    assert e["drift"] == 0.0
    assert e["drift_status"] == "green"


def test_drift_routes_todo_and_counts_attention(seeded_db):
    acc = _account(seeded_db, name="Карта", owner_user_id=USER_ID)
    _snap(seeded_db, acc.id, days_ago=10, balance=1000)
    _snap(seeded_db, acc.id, days_ago=2, balance=800)
    out = FinanceService(seeded_db).data_health(str(HOUSEHOLD_ID), current_user_id=str(USER_ID))
    me = next(p for p in out["people"] if p["is_you"])
    assert any(t["kind"] == "drift" and "Карта" in t["label"] for t in me["todos"])
