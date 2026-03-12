from __future__ import annotations

import hashlib
import re
import uuid
from datetime import datetime, timezone
from decimal import Decimal

from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message

from app.application.services.finance_service import FinanceService
from app.domain.enums import Currency, TransactionDirection
from app.infrastructure.db.models import Transaction, User
from app.infrastructure.db.session import SessionLocal

router = Router()
EXPENSE_RE = re.compile(r"^\s*(\d+(?:[\.,]\d{1,2})?)\s+(.{2,})$", re.IGNORECASE)


def _tx_fingerprint(household_id: str, amount: Decimal, merchant: str) -> str:
    payload = f"{household_id}|{datetime.now(timezone.utc).date().isoformat()}|{amount}|{merchant.strip().lower()}|telegram"
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _find_user(db, telegram_id: str):
    return db.query(User).filter(User.telegram_id == telegram_id, User.is_active.is_(True)).first()


@router.message(Command("month"))
async def month_command(message: Message):
    with SessionLocal() as db:
        user = _find_user(db, str(message.from_user.id)) if message.from_user else None
        if not user:
            await message.answer("User not linked. Seed users table first.")
            return
        summary = FinanceService(db).month_summary(str(user.household_id))

    tops = "\n".join([f"• {x['category']}: {x['amount']}" for x in summary["top_categories"][:3]]) or "• no data"
    upcoming = "\n".join([f"• {x['due_date']} {x['title']} {x['amount']} {x['currency']}" for x in summary["upcoming_until_month_end"][:3]]) or "• none"
    await message.answer(
        "\n".join(
            [
                f"MTD spend: {summary['totals']['spend_mtd']}",
                f"MTD income: {summary['totals']['income_mtd']}",
                "Top categories:",
                tops,
                "Upcoming till month end:",
                upcoming,
            ]
        )
    )


@router.message(Command("upcoming"))
async def upcoming_command(message: Message):
    with SessionLocal() as db:
        user = _find_user(db, str(message.from_user.id)) if message.from_user else None
        if not user:
            await message.answer("User not linked. Seed users table first.")
            return
        items = FinanceService(db).upcoming_payments(str(user.household_id), 7)

    if not items:
        await message.answer("No upcoming recurring payments for next 7 days.")
        return
    lines = [f"• {x['due_date']} | {x['title']} | {x['amount']} {x['currency']}" for x in items]
    await message.answer("Upcoming (7d):\n" + "\n".join(lines))


@router.message(Command("add"))
async def add_fallback(message: Message):
    payload = message.text.replace("/add", "", 1).strip() if message.text else ""
    await _capture_expense_text(message, payload)


@router.message()
async def default_capture(message: Message):
    text = message.text or ""
    if text.startswith("/"):
        return
    await _capture_expense_text(message, text)


async def _capture_expense_text(message: Message, text: str):
    match = EXPENSE_RE.match(text)
    if not match:
        return

    amount_raw, merchant = match.groups()
    amount = Decimal(amount_raw.replace(",", "."))

    confidence = Decimal("0.930")
    if len(merchant.strip()) < 3:
        confidence = Decimal("0.500")

    if confidence < Decimal("0.700"):
        await message.answer("Not confident enough to save. Try format: `149 biedronka`", parse_mode="Markdown")
        return

    with SessionLocal() as db:
        user = _find_user(db, str(message.from_user.id)) if message.from_user else None
        if not user:
            await message.answer("User not linked. Seed users table first.")
            return
        fingerprint = _tx_fingerprint(str(user.household_id), amount, merchant)
        duplicate = db.query(Transaction).filter(Transaction.dedup_fingerprint == fingerprint).first()
        if duplicate:
            await message.answer("Looks like duplicate, skipped.")
            return

        tx = Transaction(
            id=uuid.uuid4(),
            household_id=user.household_id,
            user_id=user.id,
            direction=TransactionDirection.EXPENSE,
            amount=amount,
            currency=Currency.USD,
            occurred_at=datetime.now(timezone.utc),
            merchant_raw=merchant.strip(),
            description_raw=text,
            source="telegram",
            parse_status="ok",
            parse_confidence=confidence,
            dedup_fingerprint=fingerprint,
        )
        db.add(tx)
        db.commit()

    await message.answer(f"Saved expense: {amount} {Currency.USD.value} — {merchant.strip()}")
