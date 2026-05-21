from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message

from app.api.routers.auth import sign_magic
from app.infrastructure.config.settings import get_settings
from app.infrastructure.db.models import User
from app.infrastructure.db.session import SessionLocal

router = Router()


@router.message(Command("dashboard", "login"))
async def dashboard_cmd(message: Message) -> None:
    if message.from_user is None:
        return
    tg_id = str(message.from_user.id)

    with SessionLocal() as db:
        user = db.query(User).filter(User.telegram_id == tg_id, User.is_active.is_(True)).one_or_none()

    if user is None:
        await message.answer("Нет доступа. Свяжись с владельцем дашборда.")
        return

    token = sign_magic(str(user.id), str(user.household_id))
    url = f"{get_settings().dashboard_url.rstrip('/')}/auth/tg?t={token}"
    await message.answer(
        f"Ссылка для входа (5 минут):\n{url}",
        disable_web_page_preview=True,
    )
