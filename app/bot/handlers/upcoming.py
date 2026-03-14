"""
upcoming.py — /upcoming command handler.

Shows all transactions with occurred_at > today.
Any future-dated transaction = planned activity.
"""
from __future__ import annotations

from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message

from app.application.services.finance_service import FinanceService
from app.infrastructure.db.models import User
from app.infrastructure.db.session import SessionLocal

router = Router()


def _find_user(db, telegram_id: str):
    return db.query(User).filter(User.telegram_id == telegram_id, User.is_active.is_(True)).first()


async def send_upcoming(message: Message, telegram_id: str) -> None:
    """Shared logic for /upcoming and month button."""
    with SessionLocal() as db:
        user = _find_user(db, telegram_id)
        if not user:
            await message.answer(
                "⚠️ Я не вижу твой профиль в этом household.\n\n"
                "Нужно привязать Telegram-аккаунт к пользователю HastleFam.\n"
                "Если это твой бот — проверь привязку в базе."
            )
            return
        items = FinanceService(db).upcoming_transactions(str(user.household_id))

    if not items:
        await message.answer("🗓 Нет запланированных платежей.")
        return

    direction_icon = {"expense": "💸", "income": "💰"}
    lines = [
        f"• {x['due_date']} · {direction_icon.get(x['direction'], '•')} {x['amount']} {x['currency']} · {x['title']}"
        + (f" #{x['primary_tag']}" if x.get("primary_tag") else "")
        for x in items
    ]
    await message.answer("🗓 Запланировано\n\n" + "\n".join(lines))


@router.message(Command("upcoming"))
async def upcoming_command(message: Message):
    await send_upcoming(message, str(message.from_user.id) if message.from_user else "")
