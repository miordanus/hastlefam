"""Service-layer tests for web transaction create/edit (Task 2)."""
from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal

from app.application.services.finance_service import FinanceService
from app.domain.enums import Currency, TransactionDirection
from app.infrastructure.db.models import Transaction
from tests.conftest import ACCOUNT_ID, HOUSEHOLD_ID, USER_ID


def test_create_transaction_persists_core_fields(seeded_db):
    svc = FinanceService(seeded_db)
    tx = svc.create_transaction(
        household_id=str(HOUSEHOLD_ID),
        amount=Decimal("500"),
        currency="RUB",
        direction="expense",
        occurred_at=date(2026, 5, 10),
        primary_tag="#Еда",
        account_id=str(ACCOUNT_ID),
        merchant="Пятёрочка",
        user_id=str(USER_ID),
    )
    row = seeded_db.get(Transaction, tx.id)
    assert row is not None
    assert row.amount == Decimal("500")
    assert row.currency == Currency.RUB
    assert row.direction == TransactionDirection.EXPENSE
    assert row.primary_tag == "еда"            # stripped '#', lowercased
    assert row.source == "web"
    assert row.is_planned is False
    assert row.is_internal_transfer is False
    assert row.account_id == ACCOUNT_ID


def test_create_transaction_sets_dedup_fingerprint(seeded_db):
    svc = FinanceService(seeded_db)
    tx = svc.create_transaction(
        household_id=str(HOUSEHOLD_ID), amount=Decimal("10"), currency="USD",
        direction="income", occurred_at=date(2026, 5, 10), merchant="x",
    )
    assert tx.dedup_fingerprint and len(tx.dedup_fingerprint) == 64  # sha256 hex


def test_create_transaction_income_direction(seeded_db):
    svc = FinanceService(seeded_db)
    tx = svc.create_transaction(
        household_id=str(HOUSEHOLD_ID), amount=Decimal("9000"), currency="RUB",
        direction="income", occurred_at=date(2026, 5, 10),
    )
    assert seeded_db.get(Transaction, tx.id).direction == TransactionDirection.INCOME


def test_update_transaction_changes_fields(seeded_db):
    svc = FinanceService(seeded_db)
    tx = svc.create_transaction(
        household_id=str(HOUSEHOLD_ID), amount=Decimal("100"), currency="RUB",
        direction="expense", occurred_at=date(2026, 5, 1), primary_tag="старое",
    )
    updated = svc.update_transaction(
        str(tx.id), amount=Decimal("250"), primary_tag="#Новое",
        occurred_at=date(2026, 5, 9), currency="USD", direction="income",
    )
    assert updated is not None
    row = seeded_db.get(Transaction, tx.id)
    assert row.amount == Decimal("250")
    assert row.primary_tag == "новое"
    assert row.currency == Currency.USD
    assert row.direction == TransactionDirection.INCOME
    assert row.occurred_at.date() == date(2026, 5, 9)


def test_update_transaction_missing_returns_none(seeded_db):
    svc = FinanceService(seeded_db)
    assert svc.update_transaction("00000000-0000-0000-0000-0000000000aa", amount=Decimal("1")) is None


def test_update_transaction_clears_tag_with_empty_string(seeded_db):
    svc = FinanceService(seeded_db)
    tx = svc.create_transaction(
        household_id=str(HOUSEHOLD_ID), amount=Decimal("100"), currency="RUB",
        direction="expense", occurred_at=date(2026, 5, 1), primary_tag="еда",
    )
    svc.update_transaction(str(tx.id), primary_tag="")
    assert seeded_db.get(Transaction, tx.id).primary_tag is None


# ─── Tag budget upsert (Task 2 — web budget reconciliation) ──────────────────

from app.infrastructure.db.models import TagBudget  # noqa: E402


def test_upsert_tag_budget_creates(seeded_db):
    svc = FinanceService(seeded_db)
    b = svc.upsert_tag_budget(str(HOUSEHOLD_ID), "2026-05", "#Еда", Decimal("15000"))
    row = seeded_db.query(TagBudget).filter(TagBudget.id == b.id).first()
    assert row.tag == "еда"            # normalized
    assert row.month_key == "2026-05"
    assert row.limit_amount == Decimal("15000")
    assert row.currency == "RUB"       # default


def test_upsert_tag_budget_updates_existing(seeded_db):
    svc = FinanceService(seeded_db)
    svc.upsert_tag_budget(str(HOUSEHOLD_ID), "2026-05", "еда", Decimal("15000"))
    svc.upsert_tag_budget(str(HOUSEHOLD_ID), "2026-05", "еда", Decimal("20000"))
    rows = seeded_db.query(TagBudget).filter(
        TagBudget.household_id == HOUSEHOLD_ID, TagBudget.tag == "еда", TagBudget.month_key == "2026-05"
    ).all()
    assert len(rows) == 1                       # upsert, not duplicate
    assert rows[0].limit_amount == Decimal("20000")
