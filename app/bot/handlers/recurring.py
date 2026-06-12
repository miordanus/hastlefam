"""
recurring.py — /recurring command handler.

Subcommands:
  /recurring                         — list active recurring payments
  /recurring add <title> <amt> <cur> <day>   — create recurring payment
  /recurring delete <title>          — soft-delete (is_active=False)
"""
from __future__ import annotations

import calendar
import re
import uuid
from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation

from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message

from app.domain.enums import Currency, TransactionDirection
from app.infrastructure.db.models import RecurringPayment, Transaction, User
from app.infrastructure.db.session import SessionLocal

router = Router()

_CUR_SYMBOL = {"RUB": "₽", "USD": "$", "EUR": "€", "USDT": "₮", "AMD": "֏"}
_VALID_CURRENCIES = {c.value for c in Currency}


def _find_user(db, telegram_id: str):
    return db.query(User).filter(User.telegram_id == telegram_id, User.is_active.is_(True)).first()


def _next_occurrence(day_of_month: int) -> date:
    """Return the next calendar date with that day number (this month or next)."""
    today = datetime.now(timezone.utc).date()
    import calendar
    last_day = calendar.monthrange(today.year, today.month)[1]
    try:
        candidate = date(today.year, today.month, min(day_of_month, last_day))
    except ValueError:
        candidate = date(today.year, today.month, last_day)
    if candidate <= today:
        # Move to next month
        if today.month == 12:
            candidate = date(today.year + 1, 1, min(day_of_month, 31))
        else:
            last_next = calendar.monthrange(today.year, today.month + 1)[1]
            candidate = date(today.year, today.month + 1, min(day_of_month, last_next))
    return candidate


@router.message(Command("recurring"))
async def recurring_command(message: Message) -> None:
    text = (message.text or "").strip()
    # Strip command prefix
    parts = text.split(None, 1)
    args = parts[1].strip() if len(parts) > 1 else ""

    with SessionLocal() as db:
        user = _find_user(db, str(message.from_user.id)) if message.from_user else None
        if not user:
            await message.answer(
                "⚠️ Я не вижу твой профиль в этом household.\n"
                "Нужно привязать Telegram-аккаунт к пользователю HastleFam."
            )
            return
        hid = user.household_id

        if not args:
            await _handle_list(message, db, hid)
        elif args.lower().startswith("add "):
            await _handle_add(message, db, hid, args[4:].strip())
        elif args.lower().startswith("delete "):
            await _handle_delete(message, db, hid, args[7:].strip())
        else:
            await message.answer(
                "⚠️ Неизвестная команда.\n\n"
                "Варианты:\n"
                "/recurring — список\n"
                "/recurring add Netflix 49.90 USD 15\n"
                "/recurring delete Netflix"
            )


async def _handle_list(message: Message, db, hid) -> None:
    rows = (
        db.query(RecurringPayment)
        .filter(RecurringPayment.household_id == hid, RecurringPayment.is_active.is_(True))
        .order_by(RecurringPayment.next_due_date.asc())
        .all()
    )
    if not rows:
        await message.answer(
            "Список пуст.\n\n"
            "Добавить: /recurring add Netflix 49.90 USD 15"
        )
        return

    lines = ["🔁 Регулярные платежи:\n"]
    for r in rows:
        sym = _CUR_SYMBOL.get(r.currency.value, r.currency.value)
        amt = f"{r.amount_expected} {sym}" if r.amount_expected else f"? {sym}"
        day_info = f" (каждое {r.day_of_month}-е)" if r.day_of_month else ""
        next_d = r.next_due_date.strftime("%d.%m.%Y")
        lines.append(f"• {r.title} · {amt}{day_info} → следующий: {next_d}")

    await message.answer("\n".join(lines))


async def _handle_add(message: Message, db, hid, args: str) -> None:
    # Expected: <title> <amount> <currency> <day_of_month>
    # e.g. "Netflix 49.90 USD 15"
    m = re.match(
        r"^(.+?)\s+([\d.,]+)\s+([A-Za-z]+)\s+(\d{1,2})$",
        args,
    )
    if not m:
        await message.answer(
            "⚠️ Формат: /recurring add <название> <сумма> <валюта> <день>\n"
            "Пример: /recurring add Netflix 49.90 USD 15"
        )
        return

    title = m.group(1).strip()
    try:
        amount = Decimal(m.group(2).replace(",", "."))
        if amount <= 0:
            raise ValueError
    except (InvalidOperation, ValueError):
        await message.answer("⚠️ Неверная сумма.")
        return

    currency_str = m.group(3).upper()
    if currency_str not in _VALID_CURRENCIES:
        await message.answer(
            f"⚠️ Неизвестная валюта: {currency_str}\n"
            f"Поддерживаются: {', '.join(sorted(_VALID_CURRENCIES))}"
        )
        return
    currency = Currency(currency_str)

    day_of_month = int(m.group(4))
    if not 1 <= day_of_month <= 31:
        await message.answer("⚠️ День месяца должен быть от 1 до 31.")
        return

    next_due = _next_occurrence(day_of_month)
    rp = RecurringPayment(
        id=uuid.uuid4(),
        household_id=hid,
        title=title,
        amount_expected=amount,
        currency=currency,
        day_of_month=day_of_month,
        next_due_date=next_due,
        cadence="monthly",
        is_active=True,
    )
    db.add(rp)

    # Immediately create a planned transaction so it appears in /upcoming and /finance/planned
    # without waiting for the nightly recurring-reminders job (3-day lookahead).
    month_start = datetime(next_due.year, next_due.month, 1, tzinfo=timezone.utc)
    last_d = calendar.monthrange(next_due.year, next_due.month)[1]
    month_end = datetime(next_due.year, next_due.month, last_d, 23, 59, 59, tzinfo=timezone.utc)
    existing_tx = db.query(Transaction).filter(
        Transaction.household_id == hid,
        Transaction.is_planned.is_(True),
        Transaction.merchant_raw == title,
        Transaction.occurred_at >= month_start,
        Transaction.occurred_at <= month_end,
    ).first()
    if not existing_tx:
        db.add(Transaction(
            id=uuid.uuid4(),
            household_id=hid,
            direction=TransactionDirection.EXPENSE,
            amount=amount,
            currency=currency,
            occurred_at=datetime(next_due.year, next_due.month, next_due.day, tzinfo=timezone.utc),
            merchant_raw=title,
            source="recurring",
            parse_status="ok",
            is_planned=True,
            extra_tags=[],
        ))

    db.commit()

    sym = _CUR_SYMBOL.get(currency_str, currency_str)
    await message.answer(
        f"✅ Добавил регулярный платёж.\n"
        f"{title} · {amount} {sym} · каждое {day_of_month}-е\n"
        f"Следующий: {next_due.strftime('%d.%m.%Y')} — уже в /upcoming"
    )


async def _handle_delete(message: Message, db, hid, title: str) -> None:
    if not title:
        await message.answer("⚠️ Укажи название: /recurring delete Netflix")
        return

    rows = (
        db.query(RecurringPayment)
        .filter(
            RecurringPayment.household_id == hid,
            RecurringPayment.title.ilike(title),
            RecurringPayment.is_active.is_(True),
        )
        .all()
    )
    if not rows:
        await message.answer(f"⚠️ Не нашёл активный платёж с названием «{title}».")
        return

    for r in rows:
        r.is_active = False
    db.commit()

    names = ", ".join(r.title for r in rows)
    await message.answer(f"✅ Отключил: {names}. Больше не будет появляться в /upcoming.")
