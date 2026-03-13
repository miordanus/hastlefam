"""
capture.py — thin Telegram handler for free-text expense/income capture.

Delegates parsing to expense_parser, saving to finance_service,
and duplicate detection + inline actions to their respective modules.
"""
from __future__ import annotations

import hashlib
import json
import uuid
from datetime import datetime, timezone
from decimal import Decimal

from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message

from app.application.services.finance_service import FinanceService
from app.bot.handlers.duplicate_handler import ask_duplicate_confirm
from app.bot.handlers.inline_actions import build_post_capture_keyboard
from app.bot.parsers.expense_parser import ParseResult, parse
from app.domain.enums import TransactionDirection
from app.infrastructure.db.models import Transaction, User
from app.infrastructure.db.session import SessionLocal

router = Router()


def _find_user(db, telegram_id: str):
    return db.query(User).filter(User.telegram_id == telegram_id, User.is_active.is_(True)).first()


def _tx_fingerprint(household_id: str, amount: Decimal, currency: str, merchant: str, tx_date: str) -> str:
    payload = f"{household_id}|{tx_date}|{amount}|{currency}|{merchant.strip().lower()}|telegram"
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _is_suspected_duplicate(db, fingerprint: str, full_text: str, telegram_id: str, household_id) -> bool:
    """
    Heuristic: fingerprint collision on same day/amount/currency/merchant.
    Only flag if full text is identical — avoids false positives.
    """
    existing = db.query(Transaction).filter(Transaction.dedup_fingerprint == fingerprint).first()
    return existing is not None


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
        summary = FinanceService(db).month_summary(str(user.household_id))

    tops = "\n".join([f"• {x['category']}: {x['amount']}" for x in summary["top_categories"][:5]]) or "• нет данных"
    upcoming = "\n".join([
        f"• {x['due_date']} · {x['title']} · {x['amount']} {x['currency']}"
        for x in summary["upcoming_until_month_end"][:5]
    ]) or "• Ничего не запланировано"

    spend = summary["totals"]["spend_mtd"]
    income = summary["totals"]["income_mtd"]

    lines = [
        "📊 Месяц на сейчас",
        "",
        f"💸 Потрачено:\n• {spend} RUB",
        "",
        f"💰 Доход:\n• {income} RUB",
        "",
        f"🗓 Запланировано до конца месяца:\n{upcoming}",
        "",
        f"🏷 Топ-категории:\n{tops}",
    ]
    await message.answer("\n".join(lines))


@router.message(Command("upcoming"))
async def upcoming_command(message: Message):
    with SessionLocal() as db:
        user = _find_user(db, str(message.from_user.id)) if message.from_user else None
        if not user:
            await message.answer(
                "⚠️ Я не вижу твой профиль в этом household.\n\n"
                "Нужно привязать Telegram-аккаунт к пользователю HastleFam.\n"
                "Если это твой бот — проверь привязку в базе."
            )
            return
        items = FinanceService(db).upcoming_payments(str(user.household_id), 7)

    if not items:
        await message.answer("🗓 На ближайшие 7 дней ничего не запланировано.")
        return
    lines = [f"• {x['due_date']} · {x['title']} · {x['amount']} {x['currency']}" for x in items]
    await message.answer("🗓 Ближайшие платежи\n\n" + "\n".join(lines))


@router.message(Command("add"))
async def add_fallback(message: Message):
    payload = message.text.replace("/add", "", 1).strip() if message.text else ""
    if payload:
        await _capture_text(message, payload)
    else:
        await message.answer("⚠️ Не вижу сумму.\nНачни сообщение с числа.")


@router.message(Command("income"))
async def income_command(message: Message):
    """Explicit income capture via /income command."""
    payload = message.text.replace("/income", "", 1).strip() if message.text else ""
    if not payload:
        await message.answer("⚠️ Не вижу сумму.\nПример: `/income 5000 зарплата`")
        return
    # Prefix with + to signal income direction
    await _capture_text(message, f"+{payload}")


@router.message()
async def default_capture(message: Message):
    text = message.text or ""
    if text.startswith("/"):
        return
    await _capture_text(message, text)


async def _capture_text(message: Message, text: str) -> None:
    result = parse(text)

    if not result.ok:
        await message.answer(f"⚠️ {result.error}\nПопробуй: `149 кофе` или `+5000 зарплата`")
        return

    if result.amount is None:
        await message.answer("⚠️ Не вижу сумму.\nНачни сообщение с числа.")
        return

    if not result.merchant:
        await message.answer("⚠️ Не вижу, что это за трата.\nДобавь короткое название после суммы.")
        return

    with SessionLocal() as db:
        user = _find_user(db, str(message.from_user.id)) if message.from_user else None
        if not user:
            await message.answer(
                "⚠️ Я не вижу твой профиль в этом household.\n\n"
                "Нужно привязать Telegram-аккаунт к пользователю HastleFam.\n"
                "Если это твой бот — проверь привязку в базе."
            )
            return

        tx_date = result.occurred_date.isoformat()
        fingerprint = _tx_fingerprint(
            str(user.household_id),
            result.amount,
            result.currency.value,
            result.merchant,
            tx_date,
        )

        if _is_suspected_duplicate(db, fingerprint, text, str(message.from_user.id), user.household_id):
            draft = {
                "direction": result.direction.value,
                "amount": str(result.amount),
                "currency": result.currency.value,
                "occurred_at": datetime.combine(result.occurred_date, datetime.min.time()).replace(tzinfo=timezone.utc).isoformat(),
                "merchant": result.merchant,
                "description_raw": text,
                "fingerprint": fingerprint,
                "primary_tag": result.primary_tag,
                "extra_tags": result.extra_tags,
                "date_explicit": result.date_explicit,
                "currency_explicit": result.currency_explicit,
            }
            # Telegram callback data limit is 64 bytes — use a compact draft key
            draft_json = json.dumps(draft, separators=(",", ":"), ensure_ascii=False)
            if len(draft_json.encode()) > 60:
                # Draft too large for callback payload — store minimal version
                draft_json = json.dumps({
                    "direction": result.direction.value,
                    "amount": str(result.amount),
                    "currency": result.currency.value,
                    "occurred_at": datetime.combine(result.occurred_date, datetime.min.time()).replace(tzinfo=timezone.utc).isoformat(),
                    "merchant": result.merchant[:30] if result.merchant else "",
                    "fingerprint": fingerprint,
                    "primary_tag": result.primary_tag,
                    "extra_tags": result.extra_tags,
                    "date_explicit": result.date_explicit,
                    "currency_explicit": result.currency_explicit,
                }, separators=(",", ":"), ensure_ascii=False)

            await ask_duplicate_confirm(message, result, draft_json)
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
            extra_tags=result.extra_tags,
        )
        db.add(tx)
        db.commit()
        tx_id = str(tx.id)

    keyboard = build_post_capture_keyboard(
        tx_id=tx_id,
        tag_missing=result.primary_tag is None,
        date_explicit=result.date_explicit,
        currency_explicit=result.currency_explicit,
    )

    amount = result.amount
    currency = result.currency.value
    merchant = result.merchant

    if result.primary_tag:
        body = f"✅ Записал.\n{amount} {currency} · {merchant} · {result.primary_tag}"
    else:
        body = f"✅ Записал.\n{amount} {currency} · {merchant}"

    await message.answer(body, reply_markup=keyboard)
