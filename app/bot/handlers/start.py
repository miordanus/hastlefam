from aiogram import Router
from aiogram.filters import CommandStart
from aiogram.types import Message

from app.infrastructure.db.models import User
from app.infrastructure.db.session import SessionLocal

router = Router()


def _find_user(db, telegram_id: str):
    return db.query(User).filter(User.telegram_id == telegram_id, User.is_active.is_(True)).first()


@router.message(CommandStart())
async def start(message: Message):
    with SessionLocal() as db:
        user = _find_user(db, str(message.from_user.id)) if message.from_user else None

    if not user:
        await message.answer(
            "⚠️ Я не вижу твой профиль в этом household.\n\n"
            "Нужно привязать Telegram-аккаунт к пользователю HastleFam.\n"
            "Если это твой бот — проверь привязку в базе."
        )
        return

    await message.answer(
        "💰 HastleFam на связи.\n\n"
        "Просто напиши сумму и название:\n"
        "  `149 biedronka`\n"
        "  `49.90 netflix EUR`\n"
        "  `+5000 зарплата`"
    )
