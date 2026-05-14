"""Tests for recurring_reminders — _already_sent() dedup logic."""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import sqlalchemy

from app.application.jobs.recurring_reminders import _already_sent
from app.domain.enums import Currency, TransactionDirection
from app.infrastructure.db.models import EventLog, Transaction
from tests.conftest import HOUSEHOLD_ID


def _make_planned_tx(db, occurred_at, merchant="аренда", amount=5000):
    tx = Transaction(
        id=uuid.uuid4(),
        household_id=HOUSEHOLD_ID,
        direction=TransactionDirection.EXPENSE,
        amount=amount,
        currency=Currency.RUB,
        occurred_at=occurred_at,
        merchant_raw=merchant,
        source="telegram",
        parse_status="ok",
        is_planned=True,
        extra_tags=[],
    )
    db.add(tx)
    db.flush()
    return tx


def test_already_sent_returns_false_with_no_log(seeded_db):
    tx = _make_planned_tx(seeded_db, datetime.now(timezone.utc) + timedelta(days=2))
    seeded_db.commit()
    assert _already_sent(seeded_db, HOUSEHOLD_ID, tx.id) is False


def test_already_sent_returns_true_after_log_written(seeded_db):
    tx = _make_planned_tx(seeded_db, datetime.now(timezone.utc) + timedelta(days=2))
    seeded_db.add(EventLog(
        household_id=HOUSEHOLD_ID,
        user_id=None,
        event_type="recurring_reminder_sent",
        entity_type="planned_transaction",
        entity_id=tx.id,
        payload={},
        severity="info",
    ))
    seeded_db.commit()
    assert _already_sent(seeded_db, HOUSEHOLD_ID, tx.id) is True


def test_already_sent_ignores_stale_log(seeded_db):
    tx = _make_planned_tx(seeded_db, datetime.now(timezone.utc) + timedelta(days=2))
    log = EventLog(
        household_id=HOUSEHOLD_ID,
        user_id=None,
        event_type="recurring_reminder_sent",
        entity_type="planned_transaction",
        entity_id=tx.id,
        payload={},
        severity="info",
    )
    seeded_db.add(log)
    seeded_db.flush()
    stale_time = datetime.now(timezone.utc) - timedelta(hours=25)
    # SQLite stores UUIDs as hex (no hyphens) and datetimes without timezone;
    # use log.id.hex for the WHERE clause and a naive UTC string for the value.
    seeded_db.execute(
        sqlalchemy.text("UPDATE event_log SET created_at = :t WHERE id = :id"),
        {"t": stale_time.strftime("%Y-%m-%d %H:%M:%S.%f"), "id": log.id.hex},
    )
    seeded_db.commit()
    seeded_db.expire_all()  # flush ORM identity-map cache so the query hits SQLite
    assert _already_sent(seeded_db, HOUSEHOLD_ID, tx.id) is False
