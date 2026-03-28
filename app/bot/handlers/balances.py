"""
balances.py — /balances command handler.

Manual balance snapshot / reconcile feature.
The user enters what they actually see in their account.
The bot shows the delta before saving (reconcile confirmation step).

Batch 1: renamed ✏️ Обновить → 🔄 Сверить, added reconcile confirm step, Net Worth label.
Batch 2: added 📋 История button per account (running balance from last snapshot).
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

from app.application.services.finance_service import FinanceService
from app.application.services.fx_service import convert_to_rub
from app.domain.enums import TransactionDirection
from app.infrastructure.db.models import Account, BalanceSnapshot, Transaction, User
from app.infrastructure.db.session import SessionLocal

router = Router()
log = logging.getLogger(__name__)

_CB_RECONCILE = "bal:reconcile:"    # bal:reconcile:{account_id}
_CB_RECONCILE_OK = "bal:reconcile_ok"
_CB_RECONCILE_CANCEL = "bal:reconcile_cancel"
_CB_HISTORY = "bal:history:"        # bal:history:{account_id}
_CB_ADD = "bal:add"                 # open add-account flow
_CB_SET_CUR = "bal:setcur:"        # bal:setcur:{currency}


class BalancesStates(StatesGroup):
    waiting_balance_amount = State()
    waiting_reconcile_confirm = State()
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


_CUR_SYMBOL = {"RUB": "\u20bd", "USD": "$", "EUR": "\u20ac", "PLN": "z\u0142", "USDT": "\u20ae"}


def _cur_sym(currency: str) -> str:
    return _CUR_SYMBOL.get(currency, currency)


def _build_accounts_keyboard(accounts: list[Account]) -> InlineKeyboardMarkup:
    rows = []
    for acc in accounts:
        rows.append([
            InlineKeyboardButton(
                text=f"🔄 Сверить: {acc.name}",
                callback_data=f"{_CB_RECONCILE}{acc.id}",
            ),
            InlineKeyboardButton(
                text="📋 История",
                callback_data=f"{_CB_HISTORY}{acc.id}",
            ),
        ])
    rows.append([InlineKeyboardButton(text="➕ Счёт", callback_data=_CB_ADD)])
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

        # Net Worth line: sum all account balances converted to RUB
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
            text += "\n\n≈ Net Worth: ~ RUB (курс недоступен)"
        else:
            formatted = f"{total_rub:,.0f}".replace(",", " ")
            text += f"\n\n≈ Net Worth: {formatted} RUB"

        keyboard = _build_accounts_keyboard(accounts)

    await message.answer(text, reply_markup=keyboard)


@router.message(Command("balances"))
async def balances_command(message: Message) -> None:
    await send_balances(message, str(message.from_user.id) if message.from_user else "")


# ─── Reconcile: enter amount ──────────────────────────────────────────────────

@router.callback_query(lambda c: c.data and c.data.startswith(_CB_RECONCILE)
                       and not c.data.startswith(_CB_RECONCILE_OK)
                       and not c.data.startswith(_CB_RECONCILE_CANCEL))
async def on_reconcile_balance(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    account_id = callback.data[len(_CB_RECONCILE):]

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

    with SessionLocal() as db:
        acc = db.query(Account).filter(Account.id == uuid.UUID(account_id)).first()
        if not acc:
            await state.clear()
            await message.answer("⚠️ Счёт не найден.")
            return
        acc_currency = acc.currency.value
        prev = _latest_snapshot(db, acc.id)
        prev_amount = Decimal(str(prev.actual_balance)) if prev else None

    # Show reconcile confirmation with delta
    await state.set_state(BalancesStates.waiting_reconcile_confirm)
    await state.update_data(pending_amount=str(amount))

    if prev_amount is not None:
        delta = amount - prev_amount
        sign = "+" if delta >= 0 else "−"
        abs_delta = abs(delta)
        direction_label = "доход" if delta >= 0 else "расход"
        confirm_text = (
            f"💼 {acc_name} · {acc_currency}\n\n"
            f"Текущий баланс по системе: {prev_amount} {acc_currency}\n"
            f"Ты вводишь: {amount} {acc_currency}\n"
            f"Расхождение: {sign}{abs_delta} {acc_currency}\n\n"
            f"Записать как {direction_label} без категории?"
        )
    else:
        confirm_text = (
            f"💼 {acc_name} · {acc_currency}\n\n"
            f"Начальный баланс: {amount} {acc_currency}\n\n"
            f"Сохранить?"
        )

    kb = InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="✅ Да", callback_data=_CB_RECONCILE_OK),
        InlineKeyboardButton(text="❌ Отмена", callback_data=_CB_RECONCILE_CANCEL),
    ]])
    await message.answer(confirm_text, reply_markup=kb)


@router.callback_query(lambda c: c.data == _CB_RECONCILE_OK)
async def on_reconcile_confirm(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    data = await state.get_data()
    account_id = data.get("account_id", "")
    acc_name = data.get("account_name", "счёт")
    pending_amount_str = data.get("pending_amount")

    if not pending_amount_str:
        await state.clear()
        await callback.message.edit_text("⚠️ Данные потеряны. Начни заново.", reply_markup=None)
        return

    amount = Decimal(pending_amount_str)
    user_id = None

    with SessionLocal() as db:
        user = _find_user(db, str(callback.from_user.id)) if callback.from_user else None
        if user:
            user_id = user.id

        acc = db.query(Account).filter(Account.id == uuid.UUID(account_id)).first()
        if not acc:
            await state.clear()
            await callback.message.edit_text("⚠️ Счёт не найден.", reply_markup=None)
            return

        prev = _latest_snapshot(db, acc.id)
        prev_amount = Decimal(str(prev.actual_balance)) if prev else None

        snapshot = BalanceSnapshot(
            id=uuid.uuid4(),
            account_id=acc.id,
            household_id=acc.household_id,
            actual_balance=amount,
            created_by_user_id=user_id,
        )
        db.add(snapshot)

        delta_tx = None
        if prev_amount is not None:
            delta = amount - prev_amount
            if delta != 0:
                from datetime import datetime, timezone as tz
                direction = TransactionDirection.INCOME if delta > 0 else TransactionDirection.EXPENSE
                delta_tx = Transaction(
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
                    primary_tag="корректировка",
                    extra_tags=[],
                    is_planned=False,
                    is_skipped=False,
                )
                db.add(delta_tx)

        db.commit()
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
    lines += ["", "Сохранено ✅"]

    await callback.message.edit_text("\n".join(lines), reply_markup=None)


@router.callback_query(lambda c: c.data == _CB_RECONCILE_CANCEL)
async def on_reconcile_cancel(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    await state.clear()
    await callback.message.edit_text("Отменено. Баланс не изменён.", reply_markup=None)
    # Re-send balances overview
    telegram_id = str(callback.from_user.id) if callback.from_user else ""
    await send_balances(callback.message, telegram_id)


# ─── History: running balance ─────────────────────────────────────────────────

@router.callback_query(lambda c: c.data and c.data.startswith(_CB_HISTORY))
async def on_account_history(callback: CallbackQuery) -> None:
    await callback.answer()
    account_id = callback.data[len(_CB_HISTORY):]

    with SessionLocal() as db:
        acc = db.query(Account).filter(Account.id == uuid.UUID(account_id)).first()
        if not acc:
            await callback.message.answer("⚠️ Счёт не найден.")
            return

        result = FinanceService(db).get_account_history(account_id)

    acc_name = acc.name
    cur = acc.currency.value

    if result["warning"] == "no_snapshot":
        await callback.message.answer(
            f"📋 {acc_name} — История\n\nНет снапшота — сначала сделай сверку (🔄 Сверить)."
        )
        return

    txns = result["transactions"]
    snap = result["snapshot"]

    lines = [f"📋 {acc_name} — История\n"]

    if not txns:
        lines.append("Транзакций после последней сверки нет.")
    else:
        for row in txns:
            sign = "+" if row["direction"] == "income" else "-"
            merchant = row["merchant"][:15].ljust(15)
            amount_str = f"{sign}{row['amount']}"
            running_str = f"{row['running_balance']}"
            lines.append(
                f"{row['date']}  {merchant}  {amount_str} {cur}  → {running_str} {cur}"
            )

    lines.append(f"\nСнапшот от {snap['date']}: {snap['amount']} {cur}")
    await callback.message.answer("\n".join(lines))


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
