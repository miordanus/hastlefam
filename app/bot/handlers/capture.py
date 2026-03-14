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

from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message

from app.bot.handlers.inline_actions import build_post_capture_keyboard
from app.bot.parsers.expense_parser import parse
from app.infrastructure.db.models import Transaction, User
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

            tx = Transaction(
                id=uuid.uuid4(),
                household_id=user.household_id,
                user_id=user.id,
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
                primary_tag=result.primary_tag,
                extra_tags=result.extra_tags or [],
            )
            db.add(tx)
            db.commit()
            tx_id = str(tx.id)

    except Exception as e:
        log.error("capture save failed: %s", e, exc_info=True)
        await message.answer("⚠️ Сейчас не получилось обработать запрос.\nПопробуй ещё раз чуть позже.")
        return

    keyboard = build_post_capture_keyboard(
        tx_id=tx_id,
        tag_missing=result.primary_tag is None,
        date_explicit=result.date_explicit,
        currency_explicit=result.currency_explicit,
    )

    from app.domain.enums import TransactionDirection as TD
    direction_label = " (доход)" if result.direction == TD.INCOME else ""

    if result.primary_tag:
        body = f"✅ Записал{direction_label}.\n{result.amount} {result.currency.value} · {result.merchant} · {result.primary_tag}"
    else:
        body = f"✅ Записал{direction_label}.\n{result.amount} {result.currency.value} · {result.merchant}"

    await message.answer(body, reply_markup=keyboard)
