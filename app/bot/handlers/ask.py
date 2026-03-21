"""/ask command — natural language queries about finances.

Usage: /ask сколько потратил на кафе за 3 месяца?
"""
from __future__ import annotations

import logging

from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message

from app.infrastructure.db.models import User
from app.infrastructure.db.session import SessionLocal

router = Router()
log = logging.getLogger(__name__)


def _find_user(db, telegram_id: str):
    return db.query(User).filter(User.telegram_id == telegram_id, User.is_active.is_(True)).first()


@router.message(Command("ask"))
async def ask_command(message: Message):
    question = (message.text or "").replace("/ask", "", 1).strip()
    if not question:
        await message.answer(
            "💬 Задай вопрос о финансах:\n\n"
            "Примеры:\n"
            "• `/ask сколько потратил на кафе за 3 месяца?`\n"
            "• `/ask какой тренд по продуктам?`\n"
            "• `/ask топ-5 мерчантов за март`\n"
            "• `/ask средний чек по ресторанам`"
        )
        return

    with SessionLocal() as db:
        user = _find_user(db, str(message.from_user.id)) if message.from_user else None
        if not user:
            await message.answer("⚠️ Профиль не найден.")
            return

        await message.answer("🔍 Анализирую...")

        from app.application.services.ask_service import ask
        answer = await ask(
            question=question,
            household_id=str(user.household_id),
            db=db,
        )

    await message.answer(answer)
