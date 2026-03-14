"""
exchange_handler.py — guided FSM for currency exchange capture.

Exchange is a separate event type: not income, not expense.
Must not appear in spend/income totals.
"""
from __future__ import annotations

import logging
import uuid
from decimal import Decimal, ROUND_HALF_UP

from aiogram import Router
from aiogram.filters import StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from app.bot.parsers.expense_parser import ParseResult
from app.domain.enums import Currency, TransactionDirection
from app.infrastructure.db.models import Transaction, User
from app.infrastructure.db.session import SessionLocal

router = Router()
log = logging.getLogger(__name__)


class ExchangeStates(StatesGroup):
    waiting_confirm_or_rate = State()


def _find_user(db, telegram_id: str):
    return db.query(User).filter(User.telegram_id == telegram_id, User.is_active.is_(True)).first()


def _calc_rate(from_amount: Decimal, to_amount: Decimal) -> Decimal:
    if from_amount and from_amount != 0:
        rate = to_amount / from_amount
        return rate.quantize(Decimal("0.000001"), rounding=ROUND_HALF_UP)
    return Decimal("0")


def _build_exchange_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="✅ Записать", callback_data="exc:confirm"),
            InlineKeyboardButton(text="✏️ Указать курс вручную", callback_data="exc:manual_rate"),
        ],
        [InlineKeyboardButton(text="❌ Отмена", callback_data="exc:cancel")],
    ])


async def handle_exchange(message: Message, result: ParseResult) -> None:
    """Entry point called from capture.py when exchange pattern is detected."""
    rate = _calc_rate(result.from_amount, result.to_amount)

    state = message.bot.get_fsm_context(message.chat.id, message.from_user.id) if hasattr(message.bot, "get_fsm_context") else None

    # We need FSM context — use the standard aiogram pattern via middleware
    # Since we can't easily get FSMContext here, use a stateless approach:
    # store draft in callback payload (fits within 64 bytes as compact form)
    # Use a session-level store keyed by (chat_id, user_id) instead
    # Simplest safe implementation: ask to confirm inline, store minimal state in callback

    summary = (
        f"💱 Обменял:\n"
        f"{result.from_amount} {result.from_currency.value} → {result.to_amount} {result.to_currency.value}\n"
        f"Курс: {rate}\n\n"
        f"Добавим курс обмена для этой операции?"
    )

    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(
                text="✅ Записать",
                callback_data=f"exc:save:{result.from_amount}:{result.from_currency.value}:{result.to_amount}:{result.to_currency.value}:{rate}",
            ),
        ],
        [InlineKeyboardButton(text="❌ Отмена", callback_data="exc:cancel")],
    ])

    await message.answer(summary, reply_markup=keyboard)


@router.callback_query(lambda c: c.data and c.data.startswith("exc:save:"))
async def on_exchange_confirm(callback: CallbackQuery) -> None:
    await callback.answer()
    parts = callback.data.split(":")
    # exc:save:{from_amount}:{from_cur}:{to_amount}:{to_cur}:{rate}
    if len(parts) < 7:
        await callback.message.edit_text("⚠️ Сейчас не получилось обработать запрос.\nПопробуй ещё раз чуть позже.", reply_markup=None)
        return

    try:
        from_amount = Decimal(parts[2])
        from_cur_str = parts[3]
        to_amount = Decimal(parts[4])
        to_cur_str = parts[5]
        rate = Decimal(parts[6])
        from_cur = Currency(from_cur_str)
        to_cur = Currency(to_cur_str)
    except Exception as e:
        log.error("exchange parse error: %s", e)
        await callback.message.edit_text("⚠️ Сейчас не получилось обработать запрос.\nПопробуй ещё раз чуть позже.", reply_markup=None)
        return

    try:
        from datetime import datetime, timezone
        with SessionLocal() as db:
            user = _find_user(db, str(callback.from_user.id)) if callback.from_user else None
            if not user:
                await callback.message.edit_text(
                    "⚠️ Бот на связи, но я не могу сохранить запись для этого пользователя.\nНужно проверить привязку аккаунта.",
                    reply_markup=None,
                )
                return

            tx = Transaction(
                id=uuid.uuid4(),
                household_id=user.household_id,
                user_id=user.id,
                direction=TransactionDirection.EXCHANGE,
                amount=from_amount,
                currency=from_cur,
                occurred_at=datetime.now(timezone.utc),
                merchant_raw=f"{from_amount} {from_cur.value} → {to_amount} {to_cur.value}",
                source="telegram",
                parse_status="ok",
                from_amount=from_amount,
                from_currency=from_cur.value,
                to_amount=to_amount,
                to_currency=to_cur.value,
                exchange_rate=rate,
                extra_tags=[],
            )
            db.add(tx)
            db.commit()

    except Exception as e:
        log.error("exchange save failed: %s", e, exc_info=True)
        await callback.message.edit_text("⚠️ Сейчас не получилось обработать запрос.\nПопробуй ещё раз чуть позже.", reply_markup=None)
        return

    await callback.message.edit_text(
        f"✅ Обмен записал.\n{from_amount} {from_cur.value} → {to_amount} {to_cur.value}\nКурс: {rate}",
        reply_markup=None,
    )


@router.callback_query(lambda c: c.data == "exc:cancel")
async def on_exchange_cancel(callback: CallbackQuery) -> None:
    await callback.answer()
    await callback.message.edit_text("Ок, не сохраняю.", reply_markup=None)
