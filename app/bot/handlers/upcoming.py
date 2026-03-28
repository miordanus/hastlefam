"""
upcoming.py — /upcoming command handler.

Shows planned transactions (is_planned=True, is_skipped=False, occurred_at > now).
Inline actions per transaction:
  ✅ Оплатил  → mark as paid (is_planned=False, occurred_at=now)
  ⏭ Пропустить → is_skipped=True, stays in DB
  📅 Перенести  → FSM: enter new date, update occurred_at
"""
from __future__ import annotations

import logging
import uuid as _uuid
from datetime import datetime, timezone

from aiogram import Router
from aiogram.filters import Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from app.application.services.finance_service import FinanceService
from app.infrastructure.db.models import Transaction, User
from app.infrastructure.db.session import SessionLocal

router = Router()
log = logging.getLogger(__name__)

_CB_PAID = "up:paid:"
_CB_SKIP = "up:skip:"
_CB_POSTPONE = "up:postpone:"


class UpcomingStates(StatesGroup):
    waiting_new_date = State()


def _find_user(db, telegram_id: str):
    return db.query(User).filter(User.telegram_id == telegram_id, User.is_active.is_(True)).first()


_DIRECTION_ICON = {"expense": "💸", "income": "💰"}


def _build_upcoming_text_and_kb(items: list[dict]) -> tuple[str, InlineKeyboardMarkup]:
    """Build message text and keyboard for upcoming list."""
    direction_icon = _DIRECTION_ICON
    lines = ["🗓 Запланировано\n"]
    rows: list[list[InlineKeyboardButton]] = []

    for x in items:
        tag_suffix = f" #{x['primary_tag']}" if x.get("primary_tag") else ""
        icon = direction_icon.get(x["direction"], "•")
        lines.append(
            f"• {x['due_date']} · {icon} {x['amount']} {x['currency']} · {x['title']}{tag_suffix}"
        )
        tx_id = x["id"]
        rows.append([
            InlineKeyboardButton(text="✅ Оплатил", callback_data=f"{_CB_PAID}{tx_id}"),
            InlineKeyboardButton(text="⏭ Пропустить", callback_data=f"{_CB_SKIP}{tx_id}"),
            InlineKeyboardButton(text="📅 Перенести", callback_data=f"{_CB_POSTPONE}{tx_id}"),
        ])

    return "\n".join(lines), InlineKeyboardMarkup(inline_keyboard=rows)


async def send_upcoming(message: Message, telegram_id: str) -> None:
    """Shared logic for /upcoming and month button."""
    with SessionLocal() as db:
        user = _find_user(db, telegram_id)
        if not user:
            await message.answer(
                "⚠️ Я не вижу твой профиль в этом household.\n\n"
                "Нужно привязать Telegram-аккаунт к пользователю HastleFam.\n"
                "Если это твой бот — проверь привязку в базе."
            )
            return
        items = FinanceService(db).upcoming_transactions(str(user.household_id))

    if not items:
        await message.answer("🗓 Нет запланированных платежей.")
        return

    text, kb = _build_upcoming_text_and_kb(items)
    await message.answer(text, reply_markup=kb)


@router.message(Command("upcoming"))
async def upcoming_command(message: Message):
    await send_upcoming(message, str(message.from_user.id) if message.from_user else "")


# ─── Mark as paid ─────────────────────────────────────────────────────────────

@router.callback_query(lambda c: c.data and c.data.startswith(_CB_PAID))
async def on_paid(callback: CallbackQuery) -> None:
    await callback.answer()
    tx_id = callback.data[len(_CB_PAID):]

    with SessionLocal() as db:
        tx = db.get(Transaction, _uuid.UUID(tx_id))
        if not tx:
            await callback.message.edit_text("⚠️ Транзакция не найдена.", reply_markup=None)
            return
        tx.is_planned = False
        tx.occurred_at = datetime.now(timezone.utc)
        db.commit()
        household_id = str(tx.household_id)

    # Refresh upcoming list
    telegram_id = str(callback.from_user.id) if callback.from_user else ""
    with SessionLocal() as db:
        user = _find_user(db, telegram_id)
        if user:
            items = FinanceService(db).upcoming_transactions(str(user.household_id))

    if not items:
        await callback.message.edit_text("✅ Оплачено. Нет больше запланированных платежей.", reply_markup=None)
        return

    text, kb = _build_upcoming_text_and_kb(items)
    await callback.message.edit_text("✅ Оплачено.\n\n" + text, reply_markup=kb)


# ─── Skip ─────────────────────────────────────────────────────────────────────

@router.callback_query(lambda c: c.data and c.data.startswith(_CB_SKIP))
async def on_skip(callback: CallbackQuery) -> None:
    await callback.answer()
    tx_id = callback.data[len(_CB_SKIP):]

    with SessionLocal() as db:
        tx = db.get(Transaction, _uuid.UUID(tx_id))
        if not tx:
            await callback.message.edit_text("⚠️ Транзакция не найдена.", reply_markup=None)
            return
        tx.is_skipped = True
        db.commit()

    # Refresh upcoming list
    telegram_id = str(callback.from_user.id) if callback.from_user else ""
    with SessionLocal() as db:
        user = _find_user(db, telegram_id)
        if user:
            items = FinanceService(db).upcoming_transactions(str(user.household_id))

    if not items:
        await callback.message.edit_text("⏭ Пропущено. Нет больше запланированных платежей.", reply_markup=None)
        return

    text, kb = _build_upcoming_text_and_kb(items)
    await callback.message.edit_text("⏭ Пропущено.\n\n" + text, reply_markup=kb)


# ─── Postpone ─────────────────────────────────────────────────────────────────

@router.callback_query(lambda c: c.data and c.data.startswith(_CB_POSTPONE))
async def on_postpone(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    tx_id = callback.data[len(_CB_POSTPONE):]

    await state.set_state(UpcomingStates.waiting_new_date)
    await state.update_data(tx_id=tx_id)
    await callback.message.answer(
        "Введи новую дату в формате ДД.ММ или ГГГГ-ММ-ДД:\n\n/cancel — отменить"
    )


@router.message(StateFilter(UpcomingStates.waiting_new_date))
async def on_new_date_input(message: Message, state: FSMContext) -> None:
    text = (message.text or "").strip()
    data = await state.get_data()
    tx_id = data.get("tx_id", "")

    # Parse date
    new_dt = None
    for fmt in ("%d.%m", "%d/%m", "%d-%m", "%Y-%m-%d"):
        try:
            parsed = datetime.strptime(text, fmt)
            if fmt == "%d.%m" or fmt == "%d/%m" or fmt == "%d-%m":
                # Use current year
                now = datetime.now(timezone.utc)
                parsed = parsed.replace(year=now.year)
            new_dt = parsed.replace(tzinfo=timezone.utc)
            break
        except ValueError:
            continue

    if new_dt is None:
        await message.answer(
            "⚠️ Не удалось распознать дату. Введи в формате ДД.ММ или ГГГГ-ММ-ДД:\n\n/cancel — отменить"
        )
        return

    with SessionLocal() as db:
        tx = db.get(Transaction, _uuid.UUID(tx_id))
        if not tx:
            await state.clear()
            await message.answer("⚠️ Транзакция не найдена.")
            return
        tx.occurred_at = new_dt
        db.commit()

    await state.clear()

    # Refresh upcoming list
    telegram_id = str(message.from_user.id) if message.from_user else ""
    with SessionLocal() as db:
        user = _find_user(db, telegram_id)
        if not user:
            await message.answer(f"📅 Перенесено на {new_dt.strftime('%d.%m.%Y')}.")
            return
        items = FinanceService(db).upcoming_transactions(str(user.household_id))

    if not items:
        await message.answer(f"📅 Перенесено на {new_dt.strftime('%d.%m.%Y')}. Нет больше запланированных платежей.")
        return

    text_out, kb = _build_upcoming_text_and_kb(items)
    await message.answer(f"📅 Перенесено на {new_dt.strftime('%d.%m.%Y')}.\n\n" + text_out, reply_markup=kb)
