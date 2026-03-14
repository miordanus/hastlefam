"""
inline_actions.py — post-capture inline action handlers.

Shows only actions that are still relevant after a transaction is saved.
Callback format: action:{action_type}:{transaction_id}
No in-memory state — all context is in the callback payload or fetched from DB.
"""
from __future__ import annotations

import uuid

from aiogram import Router
from aiogram.filters import StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from app.infrastructure.db.models import Transaction
from app.infrastructure.db.session import SessionLocal

router = Router()

_CB_PREFIX = "action:"
_CB_DONE = "action:done:"
_CB_TAG = "action:tag:"
_CB_DATE = "action:date:"
_CB_CURRENCY = "action:currency:"
_CB_PLAN = "action:plan:"


class InlineActionStates(StatesGroup):
    waiting_tag = State()
    waiting_date = State()
    waiting_currency = State()
    waiting_plan_date = State()


def build_post_capture_keyboard(
    tx_id: str,
    tag_missing: bool,
    date_explicit: bool,
    currency_explicit: bool,
) -> InlineKeyboardMarkup:
    """
    Build inline keyboard with only relevant action buttons.
    Rules from product contract:
    - if something was parsed correctly, do not over-prompt it
    - if something is missing or weak, surface the relevant action
    - always show Done
    """
    buttons: list[InlineKeyboardButton] = []

    if tag_missing:
        buttons.append(InlineKeyboardButton(text="🏷 Категория", callback_data=f"{_CB_TAG}{tx_id}"))
    # Always show date button — changing date is the most common correction
    buttons.append(InlineKeyboardButton(text="📅 Дата", callback_data=f"{_CB_DATE}{tx_id}"))
    if not currency_explicit:
        buttons.append(InlineKeyboardButton(text="💱 Валюта", callback_data=f"{_CB_CURRENCY}{tx_id}"))
    buttons.append(InlineKeyboardButton(text="✅ Готово", callback_data=f"{_CB_DONE}{tx_id}"))

    # Layout: up to 2 buttons per row, Done always last on its own row
    action_buttons = buttons[:-1]
    done_button = buttons[-1]

    rows = []
    for i in range(0, len(action_buttons), 2):
        rows.append(action_buttons[i:i + 2])
    rows.append([done_button])

    return InlineKeyboardMarkup(inline_keyboard=rows)


# ─── Done ──────────────────────────────────────────────────────────────────────

@router.callback_query(lambda c: c.data and c.data.startswith(_CB_DONE))
async def on_done(callback: CallbackQuery) -> None:
    await callback.answer()
    await callback.message.edit_reply_markup(reply_markup=None)


# ─── Tag ───────────────────────────────────────────────────────────────────────

@router.callback_query(lambda c: c.data and c.data.startswith(_CB_TAG))
async def on_tag_action(callback: CallbackQuery, state: FSMContext) -> None:
    tx_id = callback.data[len(_CB_TAG):]
    await callback.answer()
    await state.set_state(InlineActionStates.waiting_tag)
    await state.update_data(tx_id=tx_id, original_message_id=callback.message.message_id)
    await callback.message.answer(
        "🏷 Категория не заполнена.\nВыбери её сейчас, чтобы отчёт не был кривым.\n\nНапиши категорию или `#тег`:\n\n/cancel — отменить"
    )


@router.message(StateFilter(InlineActionStates.waiting_tag))
async def on_tag_input(message: Message, state: FSMContext) -> None:
    text = (message.text or "").strip()
    tag = text.lstrip("#").strip().lower()

    if not tag:
        await message.answer("⚠️ Не понял категорию. Напиши название или `#тег`.")
        return

    data = await state.get_data()
    tx_id = data.get("tx_id")
    await state.clear()

    with SessionLocal() as db:
        tx = db.query(Transaction).filter(Transaction.id == uuid.UUID(tx_id)).first()
        if tx:
            tx.primary_tag = tag
            db.commit()

    await message.answer(f"✅ Обновил запись.\nКатегория: {tag}")


# ─── Date ──────────────────────────────────────────────────────────────────────

@router.callback_query(lambda c: c.data and c.data.startswith(_CB_DATE))
async def on_date_action(callback: CallbackQuery, state: FSMContext) -> None:
    from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
    tx_id = callback.data[len(_CB_DATE):]
    await callback.answer()
    await state.set_state(InlineActionStates.waiting_date)
    await state.update_data(tx_id=tx_id)

    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="Сегодня", callback_data=f"date_choice:today:{tx_id}"),
            InlineKeyboardButton(text="Вчера", callback_data=f"date_choice:yesterday:{tx_id}"),
        ],
        [InlineKeyboardButton(text="Выбрать дату", callback_data=f"date_choice:manual:{tx_id}")],
    ])
    await callback.message.answer(
        "📅 Нужна дата.\nЭто прошло сегодня или в другой день?",
        reply_markup=keyboard,
    )


@router.callback_query(lambda c: c.data and c.data.startswith("date_choice:"))
async def on_date_choice(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    parts = callback.data.split(":")
    choice = parts[1]
    tx_id = parts[2]

    from datetime import datetime, timedelta, timezone
    today = datetime.now(timezone.utc)

    if choice == "today":
        new_date = today
        await _update_tx_date(tx_id, new_date)
        await callback.message.edit_text(
            f"✅ Дату обновил.\nТеперь запись стоит на {new_date.strftime('%d.%m.%Y')}.",
            reply_markup=None,
        )
        await state.clear()
    elif choice == "yesterday":
        new_date = today - timedelta(days=1)
        await _update_tx_date(tx_id, new_date)
        await callback.message.edit_text(
            f"✅ Дату обновил.\nТеперь запись стоит на {new_date.strftime('%d.%m.%Y')}.",
            reply_markup=None,
        )
        await state.clear()
    elif choice == "manual":
        await state.set_state(InlineActionStates.waiting_date)
        await state.update_data(tx_id=tx_id)
        await callback.message.edit_text(
            "Введи дату: 26-3 или 2026-03-26",
            reply_markup=None,
        )


@router.message(StateFilter(InlineActionStates.waiting_date))
async def on_date_input(message: Message, state: FSMContext) -> None:
    import re
    from datetime import datetime, timezone
    text = (message.text or "").strip()
    data = await state.get_data()
    tx_id = data.get("tx_id")

    parsed_date = None
    from datetime import date

    # Try ISO format first: YYYY-MM-DD
    try:
        parsed_date = date.fromisoformat(text)
    except ValueError:
        pass

    # Try short format: DD-MM, DD.MM, DD/MM
    if parsed_date is None:
        m = re.match(r"^(\d{1,2})[.\-/](\d{1,2})$", text)
        if m:
            try:
                today = datetime.now(timezone.utc).date()
                parsed_date = date(today.year, int(m.group(2)), int(m.group(1)))
            except ValueError:
                pass

    if parsed_date is None:
        await message.answer("⚠️ Не понял дату. Попробуй: 26-3 или 2026-03-26")
        return

    new_dt = datetime(parsed_date.year, parsed_date.month, parsed_date.day, tzinfo=timezone.utc)

    await _update_tx_date(tx_id, new_dt)
    await state.clear()
    await message.answer(f"✅ Дату обновил.\nТеперь запись стоит на {parsed_date.strftime('%d.%m.%Y')}.")


async def _update_tx_date(tx_id: str, new_dt) -> None:
    with SessionLocal() as db:
        tx = db.query(Transaction).filter(Transaction.id == uuid.UUID(tx_id)).first()
        if tx:
            tx.occurred_at = new_dt
            db.commit()


# ─── Currency ──────────────────────────────────────────────────────────────────

@router.callback_query(lambda c: c.data and c.data.startswith(_CB_CURRENCY))
async def on_currency_action(callback: CallbackQuery) -> None:
    from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
    tx_id = callback.data[len(_CB_CURRENCY):]
    await callback.answer()

    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="RUB", callback_data=f"cur_choice:RUB:{tx_id}"),
            InlineKeyboardButton(text="USD", callback_data=f"cur_choice:USD:{tx_id}"),
            InlineKeyboardButton(text="USDT", callback_data=f"cur_choice:USDT:{tx_id}"),
            InlineKeyboardButton(text="EUR", callback_data=f"cur_choice:EUR:{tx_id}"),
        ]
    ])
    await callback.message.answer(
        "💱 Не вижу валюту.\nВыбери валюту для этой записи.",
        reply_markup=keyboard,
    )


@router.callback_query(lambda c: c.data and c.data.startswith("cur_choice:"))
async def on_currency_choice(callback: CallbackQuery) -> None:
    await callback.answer()
    parts = callback.data.split(":")
    currency_str = parts[1]
    tx_id = parts[2]

    from app.domain.enums import Currency
    try:
        currency = Currency(currency_str)
    except ValueError:
        await callback.message.edit_text("⚠️ Неизвестная валюта.", reply_markup=None)
        return

    amount = None
    with SessionLocal() as db:
        tx = db.query(Transaction).filter(Transaction.id == uuid.UUID(tx_id)).first()
        if tx:
            tx.currency = currency
            db.commit()
            amount = tx.amount

    await callback.message.edit_text(
        f"✅ Валюту обновил.\nТеперь это {amount} {currency.value}.",
        reply_markup=None,
    )


# ─── Plan payment ──────────────────────────────────────────────────────────────

@router.callback_query(lambda c: c.data and c.data.startswith(_CB_PLAN))
async def on_plan_action(callback: CallbackQuery, state: FSMContext) -> None:
    tx_id = callback.data[len(_CB_PLAN):]
    await callback.answer()
    await state.set_state(InlineActionStates.waiting_plan_date)
    await state.update_data(tx_id=tx_id)
    await callback.message.answer(
        "🗓 Сделать из этого запланированный платёж?\n\nКогда он должен пройти?\nВведи дату: 26-3 или 2026-03-26\n\n/cancel — отменить"
    )


@router.message(StateFilter(InlineActionStates.waiting_plan_date))
async def on_plan_date_input(message: Message, state: FSMContext) -> None:
    import re as _re
    from datetime import date, datetime, timezone
    from decimal import Decimal
    text = (message.text or "").strip()
    data = await state.get_data()
    tx_id = data.get("tx_id")

    due_date = None
    try:
        due_date = date.fromisoformat(text)
    except ValueError:
        pass

    if due_date is None:
        m = _re.match(r"^(\d{1,2})[.\-/](\d{1,2})$", text)
        if m:
            try:
                today = datetime.now(timezone.utc).date()
                due_date = date(today.year, int(m.group(2)), int(m.group(1)))
            except ValueError:
                pass

    if due_date is None:
        await message.answer("⚠️ Не понял дату. Попробуй: 26-3 или 2026-03-26")
        return

    await state.clear()

    with SessionLocal() as db:
        tx = db.query(Transaction).filter(Transaction.id == uuid.UUID(tx_id)).first()
        if not tx:
            await message.answer("⚠️ Запись не найдена.")
            return

        from app.application.services.finance_service import FinanceService
        FinanceService(db).create_planned_payment(
            household_id=str(tx.household_id),
            title=tx.merchant_raw or "платёж",
            amount=Decimal(str(tx.amount)),
            currency=tx.currency,
            due_date=due_date,
            primary_tag=tx.primary_tag,
            linked_transaction_id=str(tx.id),
        )

    await message.answer(
        f"✅ Запланировал.\n{tx.amount} {tx.currency.value} · {tx.merchant_raw or 'платёж'}\nСрок: {due_date.strftime('%d.%m.%Y')}"
    )
