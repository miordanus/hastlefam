"""
upcoming.py — /upcoming command handler.
Shows planned payments for next 7 days (not recurring engine).
"""
from __future__ import annotations

import uuid

from aiogram import Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from app.application.services.finance_service import FinanceService
from app.infrastructure.db.models import User
from app.infrastructure.db.session import SessionLocal

router = Router()


def _find_user(db, telegram_id: str):
    return db.query(User).filter(User.telegram_id == telegram_id, User.is_active.is_(True)).first()


def _build_upcoming_keyboard(items: list[dict]) -> InlineKeyboardMarkup:
    """One [✅ Оплачено] button per planned item."""
    rows = []
    for item in items[:10]:
        rows.append([
            InlineKeyboardButton(
                text=f"✅ Оплачено: {item['title']}",
                callback_data=f"paid:{item['id']}",
            )
        ])
    return InlineKeyboardMarkup(inline_keyboard=rows) if rows else None


async def send_upcoming(message: Message, telegram_id: str) -> None:
    """Shared logic for sending upcoming payments — used by /upcoming and month button."""
    with SessionLocal() as db:
        user = _find_user(db, telegram_id)
        if not user:
            await message.answer(
                "⚠️ Я не вижу твой профиль в этом household.\n\n"
                "Нужно привязать Telegram-аккаунт к пользователю HastleFam.\n"
                "Если это твой бот — проверь привязку в базе."
            )
            return
        items = FinanceService(db).upcoming_planned(str(user.household_id), days=365)

    if not items:
        await message.answer("🗓 Нет запланированных платежей.")
        return

    lines = [f"• {x['due_date']} · {x['title']} · {x['amount']} {x['currency']}" for x in items]
    keyboard = _build_upcoming_keyboard(items)
    await message.answer("🗓 Ближайшие платежи\n\n" + "\n".join(lines), reply_markup=keyboard)


@router.message(Command("upcoming"))
async def upcoming_command(message: Message):
    await send_upcoming(message, str(message.from_user.id) if message.from_user else "")


@router.callback_query(lambda c: c.data and c.data.startswith("paid:"))
async def on_mark_paid(callback: CallbackQuery) -> None:
    await callback.answer()
    planned_id = callback.data[len("paid:"):]

    with SessionLocal() as db:
        user = _find_user(db, str(callback.from_user.id)) if callback.from_user else None
        if not user:
            await callback.message.edit_text(
                "⚠️ Бот на связи, но я не могу сохранить запись для этого пользователя.\nНужно проверить привязку аккаунта.",
                reply_markup=None,
            )
            return

        tx = FinanceService(db).mark_paid(
            planned_payment_id=planned_id,
            user_id=str(user.id),
            household_id=str(user.household_id),
        )

    if tx is None:
        await callback.message.edit_text("⚠️ Платёж не найден или уже отмечен.", reply_markup=None)
        return

    await callback.message.edit_text(
        f"✅ Записал оплату.\n{tx.amount} {tx.currency.value} · {tx.merchant_raw}",
        reply_markup=None,
    )
