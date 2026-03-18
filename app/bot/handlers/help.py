from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message

router = Router()


@router.message(Command("help"))
async def help_cmd(message: Message):
    await message.answer(
        "🧾 Что я умею\n\n"
        "📝 Запись:\n"
        "• `149 supermarket` — трата\n"
        "• `49.90 netflix EUR` — трата в валюте\n"
        "• `+5000 зарплата` — доход\n"
        "• `120 taxi #transport` — трата с тегом\n"
        "• `/add 149 supermarket` — явный ввод\n\n"
        "📊 Отчёты:\n"
        "• `/month` — итоги месяца\n"
        "• `/upcoming` — ближайшие платежи\n"
        "• `/inbox` — записи без тега\n\n"
        "💼 Счета:\n"
        "• `/balances` — балансы счетов\n\n"
        "⚙️ Прочее:\n"
        "• `/cancel` — отменить текущий ввод\n"
        "• `/help` — эта подсказка\n\n"
        "Валюты: RUB · USD · USDT · EUR\n"
        "По умолчанию: RUB"
    )
