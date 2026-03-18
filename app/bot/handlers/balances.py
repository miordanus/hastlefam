"""
balances.py — /balances command handler.

Manual balance snapshot / checkpoint feature.
The user enters what they actually see in their account.
The bot stores it and shows the delta vs the previous snapshot.

This is NOT reconciliation. There is no expected-balance calculation.
Account transaction attribution is too sparse for that to be reliable.
"""
from __future__ import annotations

import logging
import uuid
from decimal import Decimal, InvalidOperation

from aiogram import Router
from aiogram.filters import Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from app.application.services.fx_service import convert_to_rub
from app.domain.enums import TransactionDirection
from app.infrastructure.db.models import Account, BalanceSnapshot, Transaction, User
from app.infrastructure.db.session import SessionLocal

router = Router()
log = logging.getLogger(__name__)

_CB_UPDATE = "bal:update:"      # bal:update:{account_id}
_CB_ADD = "bal:add"             # open add-account flow
_CB_SET_CUR = "bal:setcur:"    # bal:setcur:{currency}


class BalancesStates(StatesGroup):
    waiting_balance_amount = State()
    waiting_account_name = State()
    waiting_account_currency = State()
    waiting_first_balance = State()


_CURRENCIES = ["RUB", "USD", "USDT", "EUR"]


def _find_user(db, telegram_id: str):
    return db.query(User).filter(User.telegram_id == telegram_id, User.is_active.is_(True)).first()


def _get_accounts(db, household_id: uuid.UUID) -> list[Account]:
    return (
        db.query(Account)
        .filter(Account.household_id == household_id, Account.is_active.is_(True))
        .order_by(Account.created_at.asc())
        .all()
    )


def _latest_snapshot(db, account_id: uuid.UUID) -> BalanceSnapshot | None:
    return (
        db.query(BalanceSnapshot)
        .filter(BalanceSnapshot.account_id == account_id)
        .order_by(BalanceSnapshot.created_at.desc())
        .first()
    )


def _prev_snapshot(db, account_id: uuid.UUID, before_id: uuid.UUID) -> BalanceSnapshot | None:
    return (
        db.query(BalanceSnapshot)
        .filter(
            BalanceSnapshot.account_id == account_id,
            BalanceSnapshot.id != before_id,
        )
        .order_by(BalanceSnapshot.created_at.desc())
        .first()
    )


def _format_accounts(accounts: list[Account], snapshots: dict[uuid.UUID, BalanceSnapshot | None]) -> str:
    if not accounts:
        return ""
    lines = []
    for acc in accounts:
        snap = snapshots.get(acc.id)
        if snap:
            date_str = snap.created_at.strftime("%d %b").lower()
            lines.append(f"• {acc.name} · {acc.currency.value} · {snap.actual_balance} · обновлено {date_str}")
        else:
            lines.append(f"• {acc.name} · {acc.currency.value} · нет данных")
    return "\n".join(lines)


def _build_accounts_keyboard(accounts: list[Account]) -> InlineKeyboardMarkup:
    rows = []
    for acc in accounts:
        rows.append([InlineKeyboardButton(
            text=f"✏️ {acc.name}",
            callback_data=f"{_CB_UPDATE}{acc.id}",
        )])
    rows.append([InlineKeyboardButton(text="➕ Добавить счёт", callback_data=_CB_ADD)])
    return InlineKeyboardMarkup(inline_keyboard=rows)


async def send_balances(message: Message, telegram_id: str) -> None:
    """Send the balances overview. Used by /balances command and month button."""
    with SessionLocal() as db:
        user = _find_user(db, telegram_id)
        if not user:
            await message.answer(
                "⚠️ Я не вижу твой профиль в этом household.\n\n"
                "Нужно привязать Telegram-аккаунт к пользователю HastleFam.\n"
                "Если это твой бот — проверь привязку в базе."
            )
            return

        accounts = _get_accounts(db, user.household_id)

        if not accounts:
            keyboard = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="➕ Добавить счёт", callback_data=_CB_ADD)]
            ])
            await message.answer("💼 Счётов пока нет.", reply_markup=keyboard)
            return

        snapshots = {acc.id: _latest_snapshot(db, acc.id) for acc in accounts}
        text = "💼 Счета\n\n" + _format_accounts(accounts, snapshots)

        # Grand total in RUB
        from datetime import date as _date
        today = _date.today()
        total_rub = Decimal("0")
        unavailable = False
        for acc in accounts:
            snap = snapshots.get(acc.id)
            if snap is None:
                continue
            bal = Decimal(str(snap.actual_balance))
            rub = convert_to_rub(bal, acc.currency.value, today, db)
            if rub is None:
                unavailable = True
            else:
                total_rub += rub
        if unavailable:
            text += "\n\n≈ ~ RUB (курс недоступен)"
        else:
            formatted = f"{total_rub:,.0f}".replace(",", " ")
            text += f"\n\n≈ {formatted} RUB"

        keyboard = _build_accounts_keyboard(accounts)

    await message.answer(text, reply_markup=keyboard)


@router.message(Command("balances"))
async def balances_command(message: Message) -> None:
    await send_balances(message, str(message.from_user.id) if message.from_user else "")


# ─── Update balance for existing account ──────────────────────────────────────

@router.callback_query(lambda c: c.data and c.data.startswith(_CB_UPDATE))
async def on_update_balance(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    account_id = callback.data[len(_CB_UPDATE):]

    with SessionLocal() as db:
        acc = db.query(Account).filter(Account.id == uuid.UUID(account_id)).first()
        if not acc:
            await callback.message.edit_text("⚠️ Счёт не найден.", reply_markup=None)
            return
        acc_name = acc.name
        acc_currency = acc.currency.value

    await state.set_state(BalancesStates.waiting_balance_amount)
    await state.update_data(account_id=account_id, account_name=acc_name)
    await callback.message.edit_text(
        f"Введи текущий баланс ({acc_name}, {acc_currency}):\n\n/cancel — отменить",
        reply_markup=None,
    )


@router.message(StateFilter(BalancesStates.waiting_balance_amount))
async def on_balance_amount_input(message: Message, state: FSMContext) -> None:
    text = (message.text or "").strip().replace(",", ".").replace(" ", "")

    data = await state.get_data()
    account_id = data.get("account_id", "")
    acc_name = data.get("account_name", "счёт")

    try:
        amount = Decimal(text)
    except InvalidOperation:
        await message.answer(
            f"⚠️ Сейчас жду баланс для {acc_name}.\n"
            f"Введи число (например: 12000 или 450.50)\n\n"
            f"/cancel — отменить и вернуться к записи трат"
        )
        return
    user_id = None

    with SessionLocal() as db:
        user = _find_user(db, str(message.from_user.id)) if message.from_user else None
        if user:
            user_id = user.id

        acc = db.query(Account).filter(Account.id == uuid.UUID(account_id)).first()
        if not acc:
            await state.clear()
            await message.answer("⚠️ Счёт не найден.")
            return

        # Find previous snapshot for delta
        prev = _latest_snapshot(db, acc.id)

        snapshot = BalanceSnapshot(
            id=uuid.uuid4(),
            account_id=acc.id,
            household_id=acc.household_id,
            actual_balance=amount,
            created_by_user_id=user_id,
        )
        db.add(snapshot)

        # Log delta as a categorized transaction
        prev_amount = prev.actual_balance if prev else None
        if prev_amount is not None:
            delta = amount - prev_amount
            if delta != 0:
                from datetime import datetime, timezone as tz
                direction = TransactionDirection.INCOME if delta > 0 else TransactionDirection.EXPENSE
                tx = Transaction(
                    id=uuid.uuid4(),
                    household_id=acc.household_id,
                    user_id=user_id,
                    account_id=acc.id,
                    direction=direction,
                    amount=abs(delta),
                    currency=acc.currency,
                    occurred_at=datetime.now(tz.utc),
                    merchant_raw=f"Корректировка: {acc.name}",
                    source="telegram",
                    parse_status="needs_correction",
                    extra_tags=[],
                )
                db.add(tx)

        db.commit()

        acc_name = acc.name
        acc_currency = acc.currency.value

    await state.clear()

    lines = [f"💼 {acc_name} · {acc_currency}", ""]
    if prev_amount is not None:
        delta = amount - prev_amount
        sign = "+" if delta >= 0 else "−"
        abs_delta = abs(delta)
        lines += [
            f"Было: {prev_amount}",
            f"Сейчас: {amount}",
            "",
            f"Разница: {sign}{abs_delta}",
        ]
    else:
        lines.append(f"Баланс: {amount}")
    lines += ["", "Сохранено."]

    await message.answer("\n".join(lines))


# ─── Add new account ──────────────────────────────────────────────────────────

@router.callback_query(lambda c: c.data == _CB_ADD)
async def on_add_account(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    await state.set_state(BalancesStates.waiting_account_name)
    await callback.message.edit_text(
        "Как называется счёт? (например: Наличные, Тинькофф, USDT)\n\n/cancel — отменить",
        reply_markup=None,
    )


@router.message(StateFilter(BalancesStates.waiting_account_name))
async def on_account_name_input(message: Message, state: FSMContext) -> None:
    name = (message.text or "").strip()
    if not name or len(name) < 2:
        await message.answer("⚠️ Слишком короткое название. Напиши ещё раз.")
        return

    await state.update_data(account_name=name)
    await state.set_state(BalancesStates.waiting_account_currency)

    keyboard = InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text=cur, callback_data=f"{_CB_SET_CUR}{cur}")
        for cur in _CURRENCIES
    ]])
    await message.answer("Выбери валюту:", reply_markup=keyboard)


@router.callback_query(lambda c: c.data and c.data.startswith(_CB_SET_CUR))
async def on_account_currency_choice(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    currency_str = callback.data[len(_CB_SET_CUR):]

    current_state = await state.get_state()
    if current_state != BalancesStates.waiting_account_currency:
        await callback.answer()
        return

    data = await state.get_data()
    account_name = data.get("account_name", "")

    with SessionLocal() as db:
        user = _find_user(db, str(callback.from_user.id)) if callback.from_user else None
        if not user:
            await state.clear()
            await callback.message.edit_text("⚠️ Профиль не найден.", reply_markup=None)
            return

        from app.domain.enums import Currency
        try:
            currency = Currency(currency_str)
        except ValueError:
            await callback.message.edit_text("⚠️ Неизвестная валюта.", reply_markup=None)
            return

        acc = Account(
            id=uuid.uuid4(),
            household_id=user.household_id,
            owner_user_id=user.id,
            name=account_name,
            currency=currency,
            is_shared=True,
            is_active=True,
        )
        db.add(acc)
        db.commit()
        account_id = str(acc.id)

    await state.set_state(BalancesStates.waiting_balance_amount)
    await state.update_data(account_id=account_id, account_name=account_name)
    await callback.message.edit_text(
        f"Счёт создан: {account_name} · {currency_str}\n\nВведи текущий баланс:\n\n/cancel — отменить",
        reply_markup=None,
    )
