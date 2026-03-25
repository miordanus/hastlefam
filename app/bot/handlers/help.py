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
        "• `120 taxi #transport` — трата с тегом\n"
        "• `обмен 1000 USD → RUB по 90` — обмен валюты\n\n"
        "📊 Отчёты:\n"
        "• `/month` — итоги месяца (факт + план)\n"
        "• `/upcoming` — предстоящие платежи\n"
        "• `/inbox` — записи без тега\n\n"
        "💼 Счета и бюджеты:\n"
        "• `/balances` — балансы счетов\n"
        "• `/budgets` — лимиты по категориям\n\n"
        "💸 Долги:\n"
        "• `/debts` — долги (дал / взял)\n"
        "• `дал 500 Васе` — записать долг\n"
        "• `взял 1000 у Пети` — записать долг\n\n"
        "🤖 Умное:\n"
        "• `/ask <вопрос>` — спроси про финансы\n"
        "• `/rules` — правила автокатегоризации\n\n"
        "⚙️ Прочее:\n"
        "• `/cancel` — отменить текущий ввод\n"
        "• `/help` — эта подсказка\n\n"
        "Валюты: RUB · USD · USDT · EUR · AMD\n"
        "По умолчанию: RUB"
    )
