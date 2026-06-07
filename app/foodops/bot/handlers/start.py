from aiogram import Router
from aiogram.filters import Command, CommandStart
from aiogram.types import Message

from app.foodops.bot.handlers.common import find_user

router = Router()

_WELCOME = (
    "🥦 FoodOps на связи.\n\n"
    "Пиши голосом или текстом, что дома и что нужно — можно много сразу:\n"
    "  «молоко почти закончилось, яйца 4 штуки, кофе закончился, "
    "добавь курицу и сыр в список»\n\n"
    "Спросить список: «что купить?»"
)

_NO_USER = (
    "⚠️ Не вижу твой профиль в household.\n"
    "Нужно привязать Telegram-аккаунт к пользователю. Проверь привязку в базе."
)


@router.message(CommandStart())
@router.message(Command("help"))
async def start(message: Message):
    user = find_user(str(message.from_user.id)) if message.from_user else None
    await message.answer(_WELCOME if user else _NO_USER)
