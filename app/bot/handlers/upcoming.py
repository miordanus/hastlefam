"""
upcoming.py — /upcoming command handler.

Shows planned transactions (is_planned=True, is_skipped=False, occurred_at > now).
Inline action per transaction:
  ✅ (button) → mark as paid (is_planned=False, is_skipped=False, occurred_at=now)

Each transaction row has exactly one ✅ button.  Pressing it marks the row as
paid and replaces its icon with ☑️ (no button), while remaining rows keep their
✅ button.  The whole view is ONE message that gets edited in-place.
"""
from __future__ import annotations

import logging
import uuid as _uuid
from datetime import datetime, timezone
from decimal import Decimal

from aiogram import Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from app.application.services.finance_service import FinanceService
from app.infrastructure.db.models import Transaction, User
from app.infrastructure.db.session import SessionLocal

router = Router()
log = logging.getLogger(__name__)

_CB_PAID = "paid:"

_DIRECTION_ICON = {"expense": "💸", "income": "💰"}


def _find_user(db, telegram_id: str):
    return db.query(User).filter(User.telegram_id == telegram_id, User.is_active.is_(True)).first()


def _fmt_amount(amount: Decimal | str) -> str:
    """Format amount with thousands separator, strip trailing zeros."""
    val = Decimal(str(amount))
    # Show as integer if no fractional part, else 2 decimal places
    if val == val.to_integral_value():
        return f"{int(val):,}".replace(",", " ")
    return f"{float(val):,.2f}".replace(",", " ")


def _build_upcoming_text_and_kb(
    items: list[dict],
    paid_item: dict | None = None,
) -> tuple[str, InlineKeyboardMarkup]:
    """Build message text + keyboard.

    paid_item: just-paid transaction to show as ☑️ without a button.
    items: remaining unpaid transactions, each gets a ✅ button row.
    """
    lines: list[str] = ["🗓 Запланировано\n"]
    rows: list[list[InlineKeyboardButton]] = []

    if paid_item:
        icon = _DIRECTION_ICON.get(paid_item["direction"], "•")
        tag_suffix = f" #{paid_item['primary_tag']}" if paid_item.get("primary_tag") else ""
        lines.append(
            f"☑️ {_fmt_amount(paid_item['amount'])} {paid_item['currency']} · {paid_item['title']}{tag_suffix}"
        )

    for x in items:
        icon = _DIRECTION_ICON.get(x["direction"], "•")
        tag_suffix = f" #{x['primary_tag']}" if x.get("primary_tag") else ""
        lines.append(
            f"{icon} {_fmt_amount(x['amount'])} {x['currency']} · {x['title']}{tag_suffix}"
        )
        rows.append([
            InlineKeyboardButton(text="✅", callback_data=f"{_CB_PAID}{x['id']}"),
        ])

    return "\n".join(lines), InlineKeyboardMarkup(inline_keyboard=rows)


async def send_upcoming(message: Message, telegram_id: str) -> None:
    """Shared logic for /upcoming and month button."""
    with SessionLocal() as db:
        user = _find_user(db, telegram_id)
        if not user:
            await message.answer(
                "⚠️ Я не вижу твой профиль в этом household.\n\n"
                "Нужно привязать Telegram-аккаунт к пользователю HastleFam.\n"
                "Если это твой бот — проверь привязку в базе."
            )
            return
        items = FinanceService(db).upcoming_transactions(str(user.household_id))

    if not items:
        await message.answer("🗓 Нет запланированных платежей.")
        return

    text, kb = _build_upcoming_text_and_kb(items)
    await message.answer(text, reply_markup=kb)


@router.message(Command("upcoming"))
async def upcoming_command(message: Message):
    await send_upcoming(message, str(message.from_user.id) if message.from_user else "")


# ─── Mark as paid ─────────────────────────────────────────────────────────────

@router.callback_query(lambda c: c.data and c.data.startswith(_CB_PAID))
async def on_paid(callback: CallbackQuery) -> None:
    await callback.answer()
    tx_id = callback.data[len(_CB_PAID):]

    paid_item: dict | None = None
    with SessionLocal() as db:
        tx = db.get(Transaction, _uuid.UUID(tx_id))
        if not tx:
            await callback.message.edit_text("⚠️ Транзакция не найдена.", reply_markup=None)
            return
        paid_item = {
            "id": tx_id,
            "title": tx.merchant_raw or "",
            "amount": tx.amount,
            "currency": tx.currency.value if tx.currency else "RUB",
            "direction": tx.direction.value,
            "primary_tag": tx.primary_tag,
        }
        tx.is_planned = False
        tx.is_skipped = False
        tx.occurred_at = datetime.now(timezone.utc)
        db.commit()

    # Re-fetch remaining planned items
    telegram_id = str(callback.from_user.id) if callback.from_user else ""
    remaining: list[dict] = []
    with SessionLocal() as db:
        user = _find_user(db, telegram_id)
        if user:
            remaining = FinanceService(db).upcoming_transactions(str(user.household_id))

    if not remaining:
        icon = _DIRECTION_ICON.get(paid_item["direction"], "•") if paid_item else "•"
        title = paid_item["title"] if paid_item else ""
        await callback.message.edit_text(
            f"☑️ {title}\n\n🗓 Больше запланированных платежей нет.",
            reply_markup=None,
        )
        return

    text, kb = _build_upcoming_text_and_kb(remaining, paid_item=paid_item)
    await callback.message.edit_text(text, reply_markup=kb)
