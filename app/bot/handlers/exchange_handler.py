"""
exchange_handler.py — currency exchange capture with account balance update.

Flow:
1. User sends "250 usdt -> 230 eur"
2. Bot confirms with rate, user clicks "✅ Записать"
3. Exchange Transaction saved to DB
4. Bot auto-matches accounts by currency:
   - Exactly 1 from-currency account + 1 to-currency account → auto-apply balance update
   - Ambiguous (multiple accounts same currency) → show account picker (FSM)
   - No matching account → skip balance update, note in confirmation
5. Balance updates: BalanceSnapshot adjustments + tagged adjustment transactions
"""
from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP

from aiogram import Router
from aiogram.filters import StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from app.bot.parsers.expense_parser import ParseResult
from app.domain.enums import Currency, TransactionDirection
from app.infrastructure.db.models import Account, BalanceSnapshot, Transaction, User
from app.infrastructure.db.session import SessionLocal

router = Router()
log = logging.getLogger(__name__)


class ExchangeStates(StatesGroup):
    waiting_from_account = State()
    waiting_to_account = State()


def _find_user(db, telegram_id: str):
    return db.query(User).filter(User.telegram_id == telegram_id, User.is_active.is_(True)).first()


def _calc_rate(from_amount: Decimal, to_amount: Decimal) -> Decimal:
    if from_amount and from_amount != 0:
        rate = to_amount / from_amount
        return rate.quantize(Decimal("0.000001"), rounding=ROUND_HALF_UP)
    return Decimal("0")


def _get_accounts_by_currency(db, household_id, currency: Currency) -> list[Account]:
    return (
        db.query(Account)
        .filter(
            Account.household_id == household_id,
            Account.currency == currency,
            Account.is_active.is_(True),
        )
        .all()
    )


def _latest_snapshot(db, account_id) -> BalanceSnapshot | None:
    return (
        db.query(BalanceSnapshot)
        .filter(BalanceSnapshot.account_id == account_id)
        .order_by(BalanceSnapshot.created_at.desc())
        .first()
    )


def _apply_balance_update(
    db,
    account: Account,
    delta: Decimal,
    user_id,
    tag: str,
    note: str,
) -> None:
    """Create a BalanceSnapshot and adjustment Transaction for one account."""
    prev = _latest_snapshot(db, account.id)
    prev_balance = prev.actual_balance if prev else Decimal("0")
    new_balance = prev_balance + delta

    snap = BalanceSnapshot(
        id=uuid.uuid4(),
        account_id=account.id,
        household_id=account.household_id,
        actual_balance=new_balance,
        created_by_user_id=user_id,
    )
    db.add(snap)

    direction = TransactionDirection.INCOME if delta > 0 else TransactionDirection.EXPENSE
    adj_tx = Transaction(
        id=uuid.uuid4(),
        household_id=account.household_id,
        user_id=user_id,
        account_id=account.id,
        direction=direction,
        amount=abs(delta),
        currency=account.currency,
        occurred_at=datetime.now(timezone.utc),
        merchant_raw=note,
        source="exchange_adjustment",
        parse_status="ok",
        primary_tag=tag,
        extra_tags=[],
    )
    db.add(adj_tx)


async def handle_exchange(message: Message, result: ParseResult) -> None:
    """Entry point called from capture.py when exchange pattern is detected."""
    rate = _calc_rate(result.from_amount, result.to_amount)

    summary = (
        f"💱 Обменял:\n"
        f"{result.from_amount} {result.from_currency.value} → {result.to_amount} {result.to_currency.value}\n"
        f"Курс: {rate}\n\n"
        f"Записать и обновить балансы счетов?"
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
async def on_exchange_confirm(callback: CallbackQuery, state: FSMContext) -> None:
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

    tx_id = None
    user_id = None
    household_id = None

    try:
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
            tx_id = str(tx.id)
            user_id = user.id
            household_id = user.household_id

    except Exception as e:
        log.error("exchange save failed: %s", e, exc_info=True)
        await callback.message.edit_text("⚠️ Сейчас не получилось обработать запрос.\nПопробуй ещё раз чуть позже.", reply_markup=None)
        return

    # ── Try auto-match accounts by currency ──────────────────────────────────
    balance_note = ""
    try:
        with SessionLocal() as db:
            from_accounts = _get_accounts_by_currency(db, household_id, from_cur)
            to_accounts = _get_accounts_by_currency(db, household_id, to_cur)

            if len(from_accounts) == 1 and len(to_accounts) == 1:
                # Perfect auto-match — apply immediately
                _apply_balance_update(
                    db, from_accounts[0], -from_amount, user_id,
                    tag="exchange", note=f"Обмен: −{from_amount} {from_cur.value}",
                )
                _apply_balance_update(
                    db, to_accounts[0], +to_amount, user_id,
                    tag="exchange", note=f"Обмен: +{to_amount} {to_cur.value}",
                )
                db.commit()
                from_name = from_accounts[0].name
                to_name = to_accounts[0].name
                balance_note = f"\n💼 Балансы обновлены:\n• {from_name}: −{from_amount}\n• {to_name}: +{to_amount}"

            elif len(from_accounts) > 1 or len(to_accounts) > 1:
                # Ambiguous — need account picker
                await state.update_data(
                    tx_id=tx_id,
                    from_amount=str(from_amount),
                    from_cur=from_cur.value,
                    to_amount=str(to_amount),
                    to_cur=to_cur.value,
                )

                if len(from_accounts) > 1:
                    # Ask which FROM account first
                    await state.set_state(ExchangeStates.waiting_from_account)
                    keyboard = InlineKeyboardMarkup(inline_keyboard=[
                        [InlineKeyboardButton(
                            text=f"💸 {acc.name}",
                            callback_data=f"excbal:from:{acc.id}",
                        )]
                        for acc in from_accounts
                    ])
                    await callback.message.edit_text(
                        f"✅ Обмен записал.\n{from_amount} {from_cur.value} → {to_amount} {to_cur.value}\nКурс: {rate}\n\n"
                        f"С какого счёта списать {from_amount} {from_cur.value}?",
                        reply_markup=keyboard,
                    )
                    return
                else:
                    # From-account is clear, need to-account
                    await state.update_data(from_account_id=str(from_accounts[0].id) if from_accounts else None)
                    await state.set_state(ExchangeStates.waiting_to_account)
                    keyboard = InlineKeyboardMarkup(inline_keyboard=[
                        [InlineKeyboardButton(
                            text=f"💰 {acc.name}",
                            callback_data=f"excbal:to:{acc.id}",
                        )]
                        for acc in to_accounts
                    ])
                    await callback.message.edit_text(
                        f"✅ Обмен записал.\n{from_amount} {from_cur.value} → {to_amount} {to_cur.value}\nКурс: {rate}\n\n"
                        f"На какой счёт зачислить {to_amount} {to_cur.value}?",
                        reply_markup=keyboard,
                    )
                    return
            # else: no matching accounts — balance_note stays empty

    except Exception as e:
        log.warning("exchange balance update failed: %s", e, exc_info=True)
        balance_note = "\n⚠️ Баланс не удалось обновить автоматически. Обнови вручную в /balances"

    await callback.message.edit_text(
        f"✅ Обмен записал.\n{from_amount} {from_cur.value} → {to_amount} {to_cur.value}\nКурс: {rate}{balance_note}",
        reply_markup=None,
    )


# ── Account picker callbacks ───────────────────────────────────────────────────

@router.callback_query(
    StateFilter(ExchangeStates.waiting_from_account),
    lambda c: c.data and c.data.startswith("excbal:from:"),
)
async def on_exchange_from_account(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    from_account_id = callback.data[len("excbal:from:"):]
    data = await state.get_data()

    await state.update_data(from_account_id=from_account_id)

    # Check if to-account also needs picking
    to_cur_str = data.get("to_cur", "")
    try:
        to_cur = Currency(to_cur_str)
    except ValueError:
        await _finish_exchange_balance(callback, state, from_account_id, None)
        return

    with SessionLocal() as db:
        user = _find_user(db, str(callback.from_user.id)) if callback.from_user else None
        if not user:
            await state.clear()
            return
        to_accounts = _get_accounts_by_currency(db, user.household_id, to_cur)
        to_account_names = [(str(a.id), a.name) for a in to_accounts]

    if len(to_account_names) == 1:
        await _finish_exchange_balance(callback, state, from_account_id, to_account_names[0][0])
    elif len(to_account_names) > 1:
        await state.set_state(ExchangeStates.waiting_to_account)
        to_amount = data.get("to_amount", "?")
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text=f"💰 {name}", callback_data=f"excbal:to:{acc_id}")]
            for acc_id, name in to_account_names
        ])
        await callback.message.edit_text(
            f"На какой счёт зачислить {to_amount} {to_cur_str}?",
            reply_markup=keyboard,
        )
    else:
        await _finish_exchange_balance(callback, state, from_account_id, None)


@router.callback_query(
    StateFilter(ExchangeStates.waiting_to_account),
    lambda c: c.data and c.data.startswith("excbal:to:"),
)
async def on_exchange_to_account(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    to_account_id = callback.data[len("excbal:to:"):]
    data = await state.get_data()
    from_account_id = data.get("from_account_id")
    await _finish_exchange_balance(callback, state, from_account_id, to_account_id)


async def _finish_exchange_balance(
    callback: CallbackQuery,
    state: FSMContext,
    from_account_id: str | None,
    to_account_id: str | None,
) -> None:
    data = await state.get_data()
    await state.clear()

    from_amount = Decimal(data.get("from_amount", "0"))
    to_amount = Decimal(data.get("to_amount", "0"))
    from_cur = data.get("from_cur", "")
    to_cur = data.get("to_cur", "")

    balance_note = ""
    try:
        with SessionLocal() as db:
            user = _find_user(db, str(callback.from_user.id)) if callback.from_user else None
            if not user:
                await callback.message.edit_text("⚠️ Профиль не найден.", reply_markup=None)
                return

            from_name = None
            to_name = None

            if from_account_id:
                from_acc = db.query(Account).filter(Account.id == uuid.UUID(from_account_id)).first()
                if from_acc:
                    _apply_balance_update(
                        db, from_acc, -from_amount, user.id,
                        tag="exchange", note=f"Обмен: −{from_amount} {from_cur}",
                    )
                    from_name = from_acc.name

            if to_account_id:
                to_acc = db.query(Account).filter(Account.id == uuid.UUID(to_account_id)).first()
                if to_acc:
                    _apply_balance_update(
                        db, to_acc, +to_amount, user.id,
                        tag="exchange", note=f"Обмен: +{to_amount} {to_cur}",
                    )
                    to_name = to_acc.name

            db.commit()

            if from_name or to_name:
                parts = []
                if from_name:
                    parts.append(f"• {from_name}: −{from_amount}")
                if to_name:
                    parts.append(f"• {to_name}: +{to_amount}")
                balance_note = "\n💼 Балансы обновлены:\n" + "\n".join(parts)

    except Exception as e:
        log.error("exchange balance finish failed: %s", e, exc_info=True)
        balance_note = "\n⚠️ Не удалось обновить балансы."

    await callback.message.edit_text(
        f"✅ Готово.{balance_note}",
        reply_markup=None,
    )


@router.callback_query(lambda c: c.data == "exc:cancel")
async def on_exchange_cancel(callback: CallbackQuery) -> None:
    await callback.answer()
    await callback.message.edit_text("Ок, не сохраняю.", reply_markup=None)
