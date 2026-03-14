"""
month.py — /month command handler.
Shows MTD spend, income, planned, top tags, and unresolved items.
Untagged items are shown separately and linked to /inbox via inline button.
Supports: /month, /month 2, /month 2026-02, and prev/next navigation buttons.
"""
from __future__ import annotations

import re
from datetime import date, datetime, timezone
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


def _parse_month_arg(text: str) -> date | None:
    """Parse month argument from command text.

    Supports:
    - /month 2       → February of current year
    - /month 02      → February of current year
    - /month 2026-02 → February 2026
    - /month 2026-2  → February 2026
    """
    arg = text.replace("/month", "", 1).strip()
    if not arg:
        return None

    # YYYY-MM or YYYY-M
    m = re.match(r"^(\d{4})-(\d{1,2})$", arg)
    if m:
        try:
            return date(int(m.group(1)), int(m.group(2)), 1)
        except ValueError:
            return None

    # Just a month number (1-12)
    m = re.match(r"^(\d{1,2})$", arg)
    if m:
        month_num = int(m.group(1))
        if 1 <= month_num <= 12:
            today = datetime.now(timezone.utc).date()
            return date(today.year, month_num, 1)

    return None


def _prev_month(d: date) -> date:
    if d.month == 1:
        return date(d.year - 1, 12, 1)
    return date(d.year, d.month - 1, 1)


def _next_month(d: date) -> date:
    if d.month == 12:
        return date(d.year + 1, 1, 1)
    return date(d.year, d.month + 1, 1)


def _build_month_keyboard(untagged_count: int, for_date: date) -> InlineKeyboardMarkup:
    rows = []

    # Navigation: ◀ prev month | ▶ next month
    prev_d = _prev_month(for_date)
    next_d = _next_month(for_date)
    rows.append([
        InlineKeyboardButton(
            text=f"◀ {_MONTH_RU[prev_d.month][:3]}",
            callback_data=f"month:nav:{prev_d.isoformat()}",
        ),
        InlineKeyboardButton(
            text=f"{_MONTH_RU[next_d.month][:3]} ▶",
            callback_data=f"month:nav:{next_d.isoformat()}",
        ),
    ])

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


def _render_month(summary: dict, for_date: date) -> tuple[str, InlineKeyboardMarkup]:
    """Render month summary text and keyboard."""
    month_label = f"{_MONTH_RU[for_date.month]} {for_date.year}"

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

    # Top actual tags only
    tags = summary["top_tags"]
    if tags:
        tag_lines = []
        for x in tags[:5]:
            by_cur = x.get("by_currency")
            if by_cur and len(by_cur) == 1:
                cur, amt = next(iter(by_cur.items()))
                tag_lines.append(f"• #{x['tag']}: {amt} {cur}")
            elif by_cur:
                parts = ", ".join(f"{amt} {cur}" for cur, amt in by_cur.items())
                tag_lines.append(f"• #{x['tag']}: {parts}")
            else:
                tag_lines.append(f"• #{x['tag']}: {x['amount']}")
        tags_block = "\n".join(tag_lines)
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

    keyboard = _build_month_keyboard(untagged, for_date)
    return "\n".join(lines), keyboard


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

        for_date = _parse_month_arg(message.text or "") or datetime.now(timezone.utc).date()
        summary = FinanceService(db).month_summary(str(user.household_id), for_date=for_date)

    text, keyboard = _render_month(summary, for_date)
    await message.answer(text, reply_markup=keyboard)


@router.callback_query(lambda c: c.data and c.data.startswith("month:nav:"))
async def on_month_navigate(callback: CallbackQuery) -> None:
    await callback.answer()
    date_str = callback.data[len("month:nav:"):]
    try:
        for_date = date.fromisoformat(date_str)
    except ValueError:
        return

    with SessionLocal() as db:
        user = _find_user(db, str(callback.from_user.id)) if callback.from_user else None
        if not user:
            return
        summary = FinanceService(db).month_summary(str(user.household_id), for_date=for_date)

    text, keyboard = _render_month(summary, for_date)
    await callback.message.edit_text(text, reply_markup=keyboard)


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
