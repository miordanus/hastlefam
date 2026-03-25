"""/debts — Debt tracking: show open debts, settle with ✅ button.

Commands:
  /debts — list open debts grouped by direction
           "Тебе должны" (they_owe) / "Ты должен" (i_owe)

Inline button:
  ✅ Вернули — set settled_at = now()
"""
from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from decimal import Decimal

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from app.domain.enums import DebtDirection
from app.infrastructure.db.models import Debt, User
from app.infrastructure.db.session import SessionLocal

router = Router()
log = logging.getLogger(__name__)

_CB_SETTLE = "debt_settle:"


def _find_user(db, telegram_id: str):
    return db.query(User).filter(User.telegram_id == telegram_id, User.is_active.is_(True)).first()


def _fmt(amount: Decimal) -> str:
    return f"{amount:,.2f}".replace(",", " ")


def _render_debts(they_owe: list, i_owe: list) -> tuple[str, InlineKeyboardMarkup]:
    lines = ["💸 <b>Долги</b>\n"]
    buttons: list[list[InlineKeyboardButton]] = []

    if they_owe:
        lines.append("📥 <b>Тебе должны:</b>")
        for d in they_owe:
            due = f"  до {d.due_date.strftime('%d.%m')}" if d.due_date else ""
            lines.append(f"  • {d.counterparty_name}: {_fmt(d.amount)} {d.currency}{due}")
            buttons.append([
                InlineKeyboardButton(
                    text=f"✅ {d.counterparty_name} вернул",
                    callback_data=f"{_CB_SETTLE}{d.id}",
                )
            ])
    else:
        lines.append("📥 Тебе никто не должен.")

    lines.append("")

    if i_owe:
        lines.append("📤 <b>Ты должен:</b>")
        for d in i_owe:
            due = f"  до {d.due_date.strftime('%d.%m')}" if d.due_date else ""
            lines.append(f"  • {d.counterparty_name}: {_fmt(d.amount)} {d.currency}{due}")
            buttons.append([
                InlineKeyboardButton(
                    text=f"✅ Вернул {d.counterparty_name}",
                    callback_data=f"{_CB_SETTLE}{d.id}",
                )
            ])
    else:
        lines.append("📤 Ты никому не должен.")

    if not they_owe and not i_owe:
        lines = ["💸 Долгов нет. Отлично! 🎉"]

    kb = InlineKeyboardMarkup(inline_keyboard=buttons) if buttons else InlineKeyboardMarkup(inline_keyboard=[])
    return "\n".join(lines), kb


@router.message(Command("debts"))
async def cmd_debts(message: Message):
    with SessionLocal() as db:
        user = _find_user(db, str(message.from_user.id)) if message.from_user else None
        if not user:
            await message.answer("⚠️ Профиль не найден.")
            return

        open_debts = (
            db.query(Debt)
            .filter(
                Debt.household_id == user.household_id,
                Debt.settled_at.is_(None),
            )
            .order_by(Debt.created_at.desc())
            .all()
        )

        they_owe = [d for d in open_debts if d.direction == DebtDirection.THEY_OWE]
        i_owe = [d for d in open_debts if d.direction == DebtDirection.I_OWE]

        text, kb = _render_debts(they_owe, i_owe)

    await message.answer(text, reply_markup=kb, parse_mode="HTML")


@router.callback_query(F.data.startswith(_CB_SETTLE))
async def cb_settle_debt(call: CallbackQuery):
    debt_id_str = call.data[len(_CB_SETTLE):]
    try:
        debt_id = uuid.UUID(debt_id_str)
    except ValueError:
        await call.answer("Ошибка: неверный ID долга.")
        return

    with SessionLocal() as db:
        debt = db.get(Debt, debt_id)
        if not debt:
            await call.answer("Долг не найден.")
            return
        if debt.settled_at:
            await call.answer("Этот долг уже закрыт.")
            return
        debt.settled_at = datetime.now(timezone.utc)
        db.commit()
        name = debt.counterparty_name
        amount = _fmt(debt.amount)
        cur = debt.currency
        direction = debt.direction

    if direction == DebtDirection.THEY_OWE:
        msg = f"✅ {name} вернул {amount} {cur}. Долг закрыт."
    else:
        msg = f"✅ Ты вернул {name} {amount} {cur}. Долг закрыт."

    await call.message.answer(msg)
    await call.answer()
