from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message

router = Router()


@router.message(Command("help"))
async def help_cmd(message: Message):
    await message.answer(
        "Send expense as plain text: `149 biedronka`\n"
        "/month - month-to-date summary\n"
        "/upcoming - recurring payments for next 7 days\n"
        "/add 49 spotify - explicit fallback"
    )
