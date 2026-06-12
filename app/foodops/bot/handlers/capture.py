"""
capture.py — catch-all FoodOps message handler.

Resolves the user, opens a session, runs the orchestration core, commits, and
replies. All domain logic lives in app.foodops.handle (framework-agnostic).
"""
from __future__ import annotations

import logging

from aiogram import Router
from aiogram.types import Message

from app.foodops import handle
from app.foodops.bot.handlers.common import find_user
from app.infrastructure.db.session import SessionLocal

router = Router()
log = logging.getLogger(__name__)

_NO_USER = (
    "⚠️ Не вижу твой профиль в household.\n"
    "Нужно привязать Telegram-аккаунт к пользователю. Проверь привязку в базе."
)


@router.message()
async def capture(message: Message):
    text = (message.text or "").strip()
    if not text or text.startswith("/"):
        return

    user = find_user(str(message.from_user.id)) if message.from_user else None
    if user is None:
        await message.answer(_NO_USER)
        return

    try:
        with SessionLocal() as db:
            reply = await handle.handle_message(db, user.household_id, user.id, text)
            db.commit()
    except Exception:
        log.exception("foodops capture failed")
        await message.answer("⚠️ Что-то пошло не так при обработке. Попробуй ещё раз.")
        return

    await message.answer(reply)
