"""
month.py — /month command handler.
Shows MTD spend, income, planned, top tags, and unresolved items.
Untagged items are shown separately and linked to /inbox via inline button.
"""
from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

from aiogram import Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from app.application.services.finance_service import FinanceService
from app.infrastructure.db.models import User
from app.infrastructure.db.session import SessionLocal

router = Router()

_MONTH_RU = {
    1: "Январь", 2: "Февраль", 3: "Март", 4: "Апрель",
    5: "Май", 6: "Июнь", 7: "Июль", 8: "Август",
    9: "Сентябрь", 10: "Октябрь", 11: "Ноябрь", 12: "Декабрь",
}


def _find_user(db, telegram_id: str):
    return db.query(User).filter(User.telegram_id == telegram_id, User.is_active.is_(True)).first()


def _format_currency_block(by_currency: dict[str, Decimal]) -> str:
    if not by_currency:
        return "• 0 RUB"
    return "\n".join(f"• {v} {cur}" for cur, v in by_currency.items())


def _build_month_keyboard(untagged_count: int) -> InlineKeyboardMarkup:
    rows = []
    if untagged_count > 0:
        rows.append([InlineKeyboardButton(
            text=f"🏷 Разобрать без тега ({untagged_count})",
            callback_data="month:open_inbox",
        )])
    rows.append([
        InlineKeyboardButton(text="🗓 Планы", callback_data="month:open_upcoming"),
        InlineKeyboardButton(text="💼 Балансы", callback_data="month:open_balances"),
    ])
    return InlineKeyboardMarkup(inline_keyboard=rows)


@router.message(Command("month"))
async def month_command(message: Message):
    with SessionLocal() as db:
        user = _find_user(db, str(message.from_user.id)) if message.from_user else None
        if not user:
            await message.answer(
                "⚠️ Я не вижу твой профиль в этом household.\n\n"
                "Нужно привязать Telegram-аккаунт к пользователю HastleFam.\n"
                "Если это твой бот — проверь привязку в базе."
            )
            return
        summary = FinanceService(db).month_summary(str(user.household_id))

    today = datetime.now(timezone.utc)
    month_label = f"{_MONTH_RU[today.month]} {today.year}"

    if summary["spend_by_currency"]:
        spend_block = _format_currency_block(summary["spend_by_currency"])
    else:
        spend_block = "• Расходов пока нет."

    if summary["income_by_currency"]:
        income_block = _format_currency_block(summary["income_by_currency"])
    else:
        income_block = "• Ничего за этот месяц."

    # Planned till month end
    planned = summary["upcoming_until_month_end"]
    if planned:
        planned_block = "\n".join(
            f"• {x['due_date']} · {x['title']} · {x['amount']} {x['currency']}"
            for x in planned[:5]
        )
    else:
        planned_block = "• Ничего не запланировано."

    # Top actual tags only — untagged items are NOT shown here
    tags = summary["top_tags"]
    if tags:
        tags_block = "\n".join(f"• #{x['tag']}: {x['amount']}" for x in tags[:5])
    else:
        tags_block = "• Тегов пока нет."

    untagged = summary.get("untagged_count", 0)

    lines = [
        f"📊 {month_label}",
        "",
        f"💸 Потрачено:\n{spend_block}",
        "",
        f"💰 Пришло:\n{income_block}",
        "",
        f"🗓 До конца месяца:\n{planned_block}",
        "",
        f"🏷 По тегам:\n{tags_block}",
    ]

    if untagged:
        lines += ["", f"⚠️ {untagged} записей без тега — нажми кнопку ниже."]

    keyboard = _build_month_keyboard(untagged)
    await message.answer("\n".join(lines), reply_markup=keyboard)


@router.callback_query(lambda c: c.data == "month:open_inbox")
async def on_month_inbox(callback: CallbackQuery) -> None:
    await callback.answer()
    from app.bot.handlers.inbox import send_inbox
    await send_inbox(callback.message, str(callback.from_user.id), edit=False)


@router.callback_query(lambda c: c.data == "month:open_upcoming")
async def on_month_upcoming(callback: CallbackQuery) -> None:
    await callback.answer()
    from app.bot.handlers.upcoming import send_upcoming
    await send_upcoming(callback.message, str(callback.from_user.id))


@router.callback_query(lambda c: c.data == "month:open_balances")
async def on_month_balances(callback: CallbackQuery) -> None:
    await callback.answer()
    from app.bot.handlers.balances import send_balances
    await send_balances(callback.message, str(callback.from_user.id))
