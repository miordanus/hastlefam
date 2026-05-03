from __future__ import annotations

import asyncio
import uuid
from datetime import date, datetime, timedelta, timezone

from aiogram import Bot
from sqlalchemy.orm import Session

from app.application.services.finance_service import FinanceService
from app.infrastructure.config.settings import get_settings
from app.infrastructure.db.models import Debt, EventLog, RecurringPayment, Transaction, User
from app.infrastructure.db.session import SessionLocal
from app.infrastructure.logging.logger import get_logger

logger = get_logger('recurring_reminders')


async def _send(bot: Bot, chat_id: int, text: str) -> None:
    await bot.send_message(chat_id=chat_id, text=text)


def run_recurring_reminders(days: int = 3) -> dict:
    settings = get_settings()
    sent = 0
    skipped = 0

    with SessionLocal() as db:
        households = [h[0] for h in db.query(User.household_id).distinct().all()]
        bot = Bot(token=settings.telegram_bot_token)
        try:
            for household_id in households:
                upcoming = FinanceService(db).upcoming_payments(str(household_id), days)
                for item in upcoming:
                    recurring_id = uuid.UUID(item["id"])
                    if _already_sent(db, household_id, recurring_id):
                        skipped += 1
                        continue
                    text = f"Reminder: {item['title']} due {item['due_date']} ({item['amount']} {item['currency']})"
                    users = db.query(User).filter(User.household_id == household_id, User.is_active.is_(True)).all()
                    for user in users:
                        try:
                            asyncio.run(_send(bot, int(user.telegram_id), text))
                        except Exception as exc:
                            logger.warning('reminder.send_failed', user_id=str(user.id), error=str(exc))
                            continue
                    db.add(
                        EventLog(
                            household_id=household_id,
                            user_id=None,
                            event_type="recurring_reminder_sent",
                            entity_type="recurring_payment",
                            entity_id=recurring_id,
                            payload={"due_date": item["due_date"], "days": days},
                            severity="info",
                        )
                    )
                    sent += 1
                # ── Debt due-date reminders ─────────────────────────────
                today = datetime.now(timezone.utc).date()
                soon = today + timedelta(days=days)
                debt_rows = db.query(Debt).filter(
                    Debt.household_id == household_id,
                    Debt.settled_at.is_(None),
                    Debt.due_date.isnot(None),
                    Debt.due_date >= today,
                    Debt.due_date <= soon,
                ).all()

                for debt in debt_rows:
                    if _debt_reminder_sent(db, household_id, debt.id):
                        skipped += 1
                        continue
                    direction_label = "ты должен" if debt.direction == "i_owe" else "тебе должны"
                    due_str = debt.due_date.strftime("%d.%m.%Y")
                    text = (
                        f"⏰ Срок долга: {direction_label} {debt.counterparty_name} "
                        f"{debt.amount} {debt.currency} до {due_str}"
                    )
                    users = db.query(User).filter(
                        User.household_id == household_id, User.is_active.is_(True)
                    ).all()
                    for user in users:
                        try:
                            asyncio.run(_send(bot, int(user.telegram_id), text))
                        except Exception as exc:
                            logger.warning("debt_reminder.send_failed", user_id=str(user.id), error=str(exc))
                    db.add(EventLog(
                        household_id=household_id,
                        user_id=None,
                        event_type="debt_reminder_sent",
                        entity_type="debt",
                        entity_id=debt.id,
                        payload={"due_date": debt.due_date.isoformat(), "days": days},
                        severity="info",
                    ))
                    sent += 1

                # ── Recurring payment → auto-create planned transaction ───────
                rp_rows = db.query(RecurringPayment).filter(
                    RecurringPayment.household_id == household_id,
                    RecurringPayment.is_active.is_(True),
                    RecurringPayment.next_due_date <= soon,
                ).all()

                import calendar as _cal
                import uuid as _uuid
                from app.domain.enums import Currency, TransactionDirection

                for rp in rp_rows:
                    nd = rp.next_due_date
                    # Check dedup: is_planned=True with same title in same month
                    month_start = datetime(nd.year, nd.month, 1, tzinfo=timezone.utc)
                    last_d = _cal.monthrange(nd.year, nd.month)[1]
                    month_end = datetime(nd.year, nd.month, last_d, 23, 59, 59, tzinfo=timezone.utc)
                    existing_tx = db.query(Transaction).filter(
                        Transaction.household_id == household_id,
                        Transaction.is_planned.is_(True),
                        Transaction.merchant_raw == rp.title,
                        Transaction.occurred_at >= month_start,
                        Transaction.occurred_at <= month_end,
                    ).first()
                    if existing_tx:
                        # Already created — just advance next_due_date
                        pass
                    else:
                        # Create planned transaction
                        occurred = datetime(nd.year, nd.month, nd.day, tzinfo=timezone.utc)
                        tx = Transaction(
                            id=_uuid.uuid4(),
                            household_id=household_id,
                            direction=TransactionDirection.EXPENSE,
                            amount=rp.amount_expected or 0,
                            currency=rp.currency,
                            occurred_at=occurred,
                            merchant_raw=rp.title,
                            source="recurring",
                            parse_status="ok",
                            is_planned=True,
                            extra_tags=[],
                        )
                        db.add(tx)

                    # Advance next_due_date by 1 month
                    next_month = nd.month + 1 if nd.month < 12 else 1
                    next_year = nd.year if nd.month < 12 else nd.year + 1
                    last_next = _cal.monthrange(next_year, next_month)[1]
                    new_day = min(rp.day_of_month or nd.day, last_next)
                    rp.next_due_date = date(next_year, next_month, new_day)

            db.commit()
        finally:
            asyncio.run(bot.session.close())

    return {"sent": sent, "skipped_duplicates": skipped}


def _already_sent(db: Session, household_id: uuid.UUID, recurring_id: uuid.UUID) -> bool:
    cutoff = datetime.now(timezone.utc) - timedelta(hours=20)
    hit = (
        db.query(EventLog)
        .filter(
            EventLog.household_id == household_id,
            EventLog.event_type == "recurring_reminder_sent",
            EventLog.entity_id == recurring_id,
            EventLog.created_at >= cutoff,
        )
        .first()
    )
    return bool(hit)


def _debt_reminder_sent(db: Session, household_id: uuid.UUID, debt_id: uuid.UUID) -> bool:
    cutoff = datetime.now(timezone.utc) - timedelta(hours=20)
    hit = (
        db.query(EventLog)
        .filter(
            EventLog.household_id == household_id,
            EventLog.event_type == "debt_reminder_sent",
            EventLog.entity_id == debt_id,
            EventLog.created_at >= cutoff,
        )
        .first()
    )
    return bool(hit)
