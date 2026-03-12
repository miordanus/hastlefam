from __future__ import annotations

import asyncio
import uuid
from datetime import datetime, timedelta, timezone

from aiogram import Bot
from sqlalchemy.orm import Session

from app.application.services.finance_service import FinanceService
from app.infrastructure.config.settings import get_settings
from app.infrastructure.db.models import EventLog, User
from app.infrastructure.db.session import SessionLocal


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
                        except Exception:
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
