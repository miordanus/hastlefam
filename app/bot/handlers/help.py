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
        "• `+5000 зарплата 25-05` — доход (если дата в будущем — кнопка [📅 В план])\n"
        "• `700 аренда 01.06-30.06` — сплит по дням\n"
        "• `обмен 1000 USD → RUB по 90` — обмен валюты\n\n"
        "📊 Отчёты:\n"
        "• `/month` — итоги месяца (факт + план)\n"
        "• `/upcoming` — предстоящие платежи\n"
        "• `/cashflow` — прогноз на 60 дней: балансы, план, долги\n"
        "• `/review` — еженедельный обзор одним экраном\n"
        "• `/inbox` — записи без тега\n\n"
        "💼 Счета и бюджеты:\n"
        "• `/balances` — балансы счетов\n"
        "• `/budgets` — лимиты по категориям\n\n"
        "💸 Долги:\n"
        "• `/debts` — долги (дал / взял)\n"
        "• `дал 500 Васе` — записать долг\n"
        "• `взял 1000 у Пети` — записать долг\n\n"
        "🔁 Регулярные платежи:\n"
        "• `/recurring` — список регулярных платежей\n"
        "• `/recurring add Netflix 49.90 USD 15` — добавить\n"
        "• `/recurring delete Netflix` — отключить\n\n"
        "🤖 Умное:\n"
        "• `/ask <вопрос>` — спроси про финансы\n"
        "• `/rules` — правила автокатегоризации\n\n"
        "⚙️ Прочее:\n"
        "• `/cancel` — отменить текущий ввод\n"
        "• `/help` — эта подсказка\n\n"
        "Валюты: RUB · USD · USDT · EUR · AMD\n"
        "По умолчанию: RUB"
    )
