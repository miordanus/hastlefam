from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message

router = Router()


@router.message(Command("help"))
async def help_cmd(message: Message):
    await message.answer(
        "🧾 Что я умею сейчас\n\n"
        "Основное:\n"
        "• просто записать трату или доход сообщением\n"
        "• помочь поправить дату, категорию, валюту и курс\n"
        "• показать, что запланировано\n"
        "• дать статус по месяцу\n\n"
        "Команды:\n"
        "• `/month` — статус месяца\n"
        "• `/upcoming` — ближайшие запланированные платежи\n"
        "• `/income` — ручной ввод дохода\n"
        "• `/add` — ручной ввод, если нужен явный формат\n"
        "• `/help` — подсказка по возможностям\n\n"
        "Формат свободного ввода:\n"
        "• `149 supermarket`\n"
        "• `49.90 netflix EUR`\n"
        "• `120 taxi #transport`\n"
        "• `+5000 зарплата` — доход\n\n"
        "Поддерживаемые валюты:\n"
        "• RUB\n"
        "• USD\n"
        "• USDT\n"
        "• EUR"
    )
