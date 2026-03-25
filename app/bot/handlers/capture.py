"""
capture.py — thin Telegram handler for free-text expense/income capture.

Delegates parsing to expense_parser; saves to DB directly.
No dedup SQL query — fingerprint is stored but not queried.
"""
from __future__ import annotations

import hashlib
import logging
import uuid
from datetime import datetime, timezone
from decimal import Decimal

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from app.bot.handlers.inline_actions import build_post_capture_keyboard
from app.bot.parsers.expense_parser import parse
from app.bot.parsers import debt_parser, split_parser
from app.infrastructure.db.models import Debt, Transaction, User
from app.infrastructure.db.session import SessionLocal

router = Router()
log = logging.getLogger(__name__)


def _find_user(db, telegram_id: str):
    return db.query(User).filter(User.telegram_id == telegram_id, User.is_active.is_(True)).first()


def _tx_fingerprint(household_id: str, amount: Decimal, currency: str, merchant: str, tx_date: str, direction: str) -> str:
    payload = f"{household_id}|{tx_date}|{amount}|{currency}|{merchant.strip().lower()}|{direction}|telegram"
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _no_user_msg() -> str:
    return (
        "⚠️ Я не вижу твой профиль в этом household.\n\n"
        "Нужно привязать Telegram-аккаунт к пользователю HastleFam.\n"
        "Если это твой бот — проверь привязку в базе."
    )


@router.message(Command("add"))
async def add_fallback(message: Message):
    payload = message.text.replace("/add", "", 1).strip() if message.text else ""
    if payload:
        await _capture_text(message, payload)
    else:
        await message.answer("⚠️ Не вижу сумму.\nНачни сообщение с числа.")


@router.message(Command("income"))
async def income_command(message: Message):
    payload = message.text.replace("/income", "", 1).strip() if message.text else ""
    if not payload:
        await message.answer("⚠️ Не вижу сумму.\nПример: `/income 5000 зарплата`")
        return
    await _capture_text(message, f"+{payload}")


@router.message()
async def default_capture(message: Message):
    text = message.text or ""
    if text.startswith("/"):
        return
    await _capture_text(message, text)


async def _capture_text(message: Message, text: str) -> None:
    # 1. Debt parser — check before expense_parser (DO NOT reorder)
    debt_result = debt_parser.parse(text)
    if debt_result is not None:
        await _handle_debt(message, debt_result)
        return

    # 2. Split parser — check before expense_parser (DO NOT reorder)
    split_result = split_parser.parse(text)
    if split_result is not None:
        await _handle_split_confirm(message, split_result)
        return

    # 3. expense_parser — main flow (DO NOT TOUCH)
    from app.bot.parsers.expense_parser import ParseResult
    result = parse(text)

    # Exchange: route to exchange handler
    if result.is_exchange:
        from app.bot.handlers.exchange_handler import handle_exchange
        await handle_exchange(message, result)
        return

    if not result.ok:
        await message.answer(f"⚠️ {result.error}")
        return

    if result.amount is None:
        await message.answer("⚠️ Не вижу сумму.\nНачни сообщение с числа.")
        return

    if not result.merchant:
        if result.amount is not None:
            await message.answer(
                f"⚠️ Записал {result.amount} — но куда?\n"
                f"Добавь название: `{result.amount} кофе`"
            )
        else:
            await message.answer("⚠️ Не вижу, что это за трата.\nДобавь короткое название после суммы.")
        return

    try:
        with SessionLocal() as db:
            user = _find_user(db, str(message.from_user.id)) if message.from_user else None
            if not user:
                await message.answer(_no_user_msg())
                return

            tx_date = result.occurred_date.isoformat()
            fingerprint = _tx_fingerprint(
                str(user.household_id),
                result.amount,
                result.currency.value,
                result.merchant,
                tx_date,
                result.direction.value,
            )

            existing = db.query(Transaction.id).filter(
                Transaction.dedup_fingerprint == fingerprint,
            ).first()
            if existing:
                await message.answer("Похоже на дубль, пропустил.")
                return

            from app.application.services.finance_service import FinanceService
            default_account = FinanceService(db).get_or_create_default_account(str(user.household_id))

            # Auto-categorization: if no tag from user, check merchant rules
            effective_tag = result.primary_tag
            autocat_applied = False
            if not effective_tag and result.merchant:
                from app.application.services.autocat_service import lookup_tag
                effective_tag = lookup_tag(db, user.household_id, result.merchant)
                if effective_tag:
                    autocat_applied = True

            tx = Transaction(
                id=uuid.uuid4(),
                household_id=user.household_id,
                user_id=user.id,
                account_id=default_account.id,
                direction=result.direction,
                amount=result.amount,
                currency=result.currency,
                occurred_at=datetime.combine(result.occurred_date, datetime.min.time()).replace(tzinfo=timezone.utc),
                merchant_raw=result.merchant,
                description_raw=text,
                source="telegram",
                parse_status="ok",
                parse_confidence=Decimal("0.930"),
                dedup_fingerprint=fingerprint,
                primary_tag=effective_tag,
                extra_tags=result.extra_tags or [],
                is_planned=False,  # ЗАКОН: capture = actual
            )
            db.add(tx)

            # Auto-learn: if user provided a tag, try to create a rule
            if result.primary_tag and result.merchant:
                from app.application.services.autocat_service import learn_from_transaction
                learn_from_transaction(db, user.household_id, result.merchant, result.primary_tag)

            db.commit()
            tx_id = str(tx.id)

    except Exception as e:
        log.error("capture save failed: %s", e, exc_info=True)
        await message.answer("⚠️ Сейчас не получилось обработать запрос.\nПопробуй ещё раз чуть позже.")
        return

    keyboard = build_post_capture_keyboard(
        tx_id=tx_id,
        tag_missing=effective_tag is None,
        date_explicit=result.date_explicit,
        currency_explicit=result.currency_explicit,
    )

    from app.domain.enums import TransactionDirection as TD
    direction_label = " (доход)" if result.direction == TD.INCOME else ""

    if effective_tag:
        auto_hint = " 🤖" if autocat_applied else ""
        body = f"✅ Записал{direction_label}.\n{result.amount} {result.currency.value} · {result.merchant} · #{effective_tag}{auto_hint}"
    else:
        body = f"✅ Записал{direction_label}.\n{result.amount} {result.currency.value} · {result.merchant}"

    await message.answer(body, reply_markup=keyboard)


# ─── Debt flow ─────────────────────────────────────────────────────────────────

async def _handle_debt(message: Message, result) -> None:
    """Save debt record and confirm to user."""
    try:
        with SessionLocal() as db:
            user = _find_user(db, str(message.from_user.id)) if message.from_user else None
            if not user:
                await message.answer(_no_user_msg())
                return

            debt = Debt(
                id=uuid.uuid4(),
                household_id=user.household_id,
                counterparty_name=result.counterparty,
                amount=result.amount,
                currency=result.currency,
                direction=result.direction.value,
            )
            db.add(debt)
            db.commit()

        from app.domain.enums import DebtDirection
        if result.direction == DebtDirection.THEY_OWE:
            msg = f"💸 Записал: {result.counterparty} должен тебе {result.amount} {result.currency}."
        else:
            msg = f"💸 Записал: ты должен {result.counterparty} {result.amount} {result.currency}."
        await message.answer(msg)

    except Exception as e:
        log.error("debt save failed: %s", e, exc_info=True)
        await message.answer("⚠️ Не удалось записать долг. Попробуй ещё раз.")


# ─── Split confirmation flow ───────────────────────────────────────────────────

_CB_SPLIT_YES = "split_yes:"
_CB_SPLIT_NO = "split_no"


async def _handle_split_confirm(message: Message, result) -> None:
    """Show split confirmation: Создать N транзакций по X RUB (DD.MM–DD.MM)?"""
    if result.n_days > 31:
        await message.answer(
            f"⚠️ Диапазон дат {result.n_days} дней — максимум 31. Уточни даты."
        )
        return

    # Encode params in callback data (compact format, ≤64 bytes)
    # split_yes:<amount>:<merchant_truncated>:<date_from>:<date_to>
    merchant_safe = result.merchant[:15].replace(":", "")
    cb_data = (
        f"{_CB_SPLIT_YES}"
        f"{result.amount}:"
        f"{merchant_safe}:"
        f"{result.date_from.isoformat()}:"
        f"{result.date_to.isoformat()}"
    )

    kb = InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="✅ Да", callback_data=cb_data),
        InlineKeyboardButton(text="❌ Нет", callback_data=_CB_SPLIT_NO),
    ]])
    fmt_from = result.date_from.strftime("%d.%m")
    fmt_to = result.date_to.strftime("%d.%m")
    await message.answer(
        f"Создать {result.n_days} транзакций по {result.amount_per_day} ₽\n"
        f"({fmt_from}–{fmt_to}) · {result.merchant}?",
        reply_markup=kb,
    )


@router.callback_query(F.data.startswith(_CB_SPLIT_YES))
async def cb_split_confirm(call: CallbackQuery) -> None:
    """Create split transactions on ✅ confirmation."""
    parts = call.data[len(_CB_SPLIT_YES):].split(":")
    if len(parts) < 4:
        await call.answer("Ошибка данных.")
        return

    try:
        amount = Decimal(parts[0])
        merchant = parts[1]
        date_from = datetime.fromisoformat(parts[2]).date()
        date_to = datetime.fromisoformat(parts[3]).date()
    except Exception:
        await call.answer("Ошибка разбора данных.")
        return

    n_days = (date_to - date_from).days + 1
    amount_per_day = (amount / n_days).quantize(Decimal("0.01"))

    try:
        with SessionLocal() as db:
            user = _find_user(db, str(call.from_user.id)) if call.from_user else None
            if not user:
                await call.message.answer(_no_user_msg())
                await call.answer()
                return

            from app.application.services.finance_service import FinanceService
            default_account = FinanceService(db).get_or_create_default_account(str(user.household_id))

            from app.domain.enums import Currency, TransactionDirection
            created = 0
            for i in range(n_days):
                from datetime import timedelta
                tx_date = date_from + timedelta(days=i)
                tx = Transaction(
                    id=uuid.uuid4(),
                    household_id=user.household_id,
                    user_id=user.id,
                    account_id=default_account.id,
                    direction=TransactionDirection.EXPENSE,
                    amount=amount_per_day,
                    currency=Currency.RUB,
                    occurred_at=datetime(tx_date.year, tx_date.month, tx_date.day, tzinfo=timezone.utc),
                    merchant_raw=merchant,
                    source="telegram",
                    parse_status="ok",
                    parse_confidence=Decimal("0.900"),
                    is_planned=False,  # ЗАКОН: split = actual
                )
                db.add(tx)
                created += 1
            db.commit()

        fmt_from = date_from.strftime("%d.%m")
        fmt_to = date_to.strftime("%d.%m")
        await call.message.answer(
            f"✅ Создал {created} транзакций по {amount_per_day} ₽\n"
            f"({fmt_from}–{fmt_to}) · {merchant}"
        )
    except Exception as e:
        log.error("split save failed: %s", e, exc_info=True)
        await call.message.answer("⚠️ Не удалось создать транзакции. Попробуй ещё раз.")

    await call.answer()


@router.callback_query(F.data == _CB_SPLIT_NO)
async def cb_split_cancel(call: CallbackQuery) -> None:
    await call.message.answer("❌ Отменено.")
    await call.answer()
