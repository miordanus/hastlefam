"""
duplicate_handler.py — duplicate suspect confirmation flow.

When a potential duplicate is detected, sends a confirmation message
with inline buttons instead of silently dropping the record.
Callback payload carries the draft transaction as a compact identifier
— no in-memory state required.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from decimal import Decimal

from aiogram import Router
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from app.bot.parsers.expense_parser import ParseResult
from app.domain.enums import TransactionDirection
from app.infrastructure.db.models import Transaction, User
from app.infrastructure.db.session import SessionLocal

router = Router()

_CB_SAVE = "dup:save:"
_CB_CANCEL = "dup:cancel"


def build_duplicate_keyboard(draft_json: str) -> InlineKeyboardMarkup:
    """Build inline keyboard for duplicate confirmation."""
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="Да, записать", callback_data=f"{_CB_SAVE}{draft_json}"),
            InlineKeyboardButton(text="Нет, отмена", callback_data=_CB_CANCEL),
        ]
    ])


async def ask_duplicate_confirm(message: Message, result: ParseResult, draft_json: str) -> None:
    """Send duplicate warning with confirmation buttons."""
    await message.answer(
        "⚠️ Похоже на повтор.\nПохожая запись уже была недавно.\nЗаписать ещё раз?",
        reply_markup=build_duplicate_keyboard(draft_json),
    )


def _find_user(db, telegram_id: str):
    return db.query(User).filter(User.telegram_id == telegram_id, User.is_active.is_(True)).first()


@router.callback_query(lambda c: c.data and c.data.startswith(_CB_SAVE))
async def on_duplicate_confirm(callback: CallbackQuery) -> None:
    """User confirmed saving the duplicate — retrieve draft from Redis and save."""
    await callback.answer()
    draft_key = callback.data[len(_CB_SAVE):]

    from app.bot import draft_store
    draft = await draft_store.retrieve(draft_key)
    if draft is None:
        await callback.message.edit_text("⚠️ Время действия кнопки истекло. Отправь запись ещё раз.")
        return

    import time
    # Modify fingerprint so a third identical send also prompts
    fingerprint = (draft.get("fingerprint") or "") + f"|confirmed|{int(time.time())}"

    with SessionLocal() as db:
        user = _find_user(db, str(callback.from_user.id)) if callback.from_user else None
        if not user:
            await callback.message.edit_text(
                "⚠️ Бот на связи, но я не могу сохранить запись для этого пользователя.\nНужно проверить привязку аккаунта."
            )
            return

        from app.domain.enums import Currency
        from app.application.services.finance_service import FinanceService
        default_account = FinanceService(db).get_or_create_default_account(str(user.household_id))
        tx = Transaction(
            id=uuid.uuid4(),
            household_id=user.household_id,
            user_id=user.id,
            account_id=default_account.id,
            direction=TransactionDirection(draft["direction"]),
            amount=Decimal(str(draft["amount"])),
            currency=Currency(draft["currency"]),
            occurred_at=datetime.fromisoformat(draft["occurred_at"]),
            merchant_raw=draft.get("merchant"),
            description_raw=draft.get("description_raw"),
            source="telegram",
            parse_status="ok",
            parse_confidence=Decimal("0.930"),
            dedup_fingerprint=fingerprint,
            primary_tag=draft.get("primary_tag"),
            extra_tags=draft.get("extra_tags", []),
            is_planned=False,
        )
        db.add(tx)
        db.commit()
        tx_id = str(tx.id)

    from app.bot.handlers.inline_actions import build_post_capture_keyboard
    keyboard = build_post_capture_keyboard(
        tx_id=tx_id,
        tag_missing=draft.get("primary_tag") is None,
        date_explicit=draft.get("date_explicit", False),
        currency_explicit=draft.get("currency_explicit", False),
    )
    amount = Decimal(str(draft["amount"]))
    currency = draft["currency"]
    merchant = draft.get("merchant") or ""
    primary_tag = draft.get("primary_tag")

    if primary_tag:
        body = f"✅ Записал ещё раз.\n{amount} {currency} · {merchant} · #{primary_tag}"
    else:
        body = f"✅ Записал ещё раз.\n{amount} {currency} · {merchant}"

    await callback.message.edit_text(body, reply_markup=keyboard)


@router.callback_query(lambda c: c.data == _CB_CANCEL)
async def on_duplicate_cancel(callback: CallbackQuery) -> None:
    """User cancelled — discard and confirm."""
    await callback.answer()
    await callback.message.edit_text("Ок, не сохраняю.")
