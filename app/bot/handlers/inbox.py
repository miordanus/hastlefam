"""
inbox.py — /inbox command handler.

Shows untagged transactions one at a time for quick tagging.
Quick-tag buttons are built from the household's most-used existing tags.
Custom tag input via FSM state.
"""
from __future__ import annotations

import logging
import uuid

from aiogram import Router
from aiogram.filters import Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from app.infrastructure.db.models import Transaction, User
from app.infrastructure.db.session import SessionLocal

router = Router()
log = logging.getLogger(__name__)

_CB_TAG = "inbox:tag:"       # inbox:tag:{tx_id}:{tag}
_CB_SKIP = "inbox:skip:"     # inbox:skip:{tx_id}
_CB_CUSTOM = "inbox:custom:" # inbox:custom:{tx_id}
_CB_DELETE = "inbox:del:"    # inbox:del:{tx_id}


class InboxStates(StatesGroup):
    waiting_custom_tag = State()


def _find_user(db, telegram_id: str):
    return db.query(User).filter(User.telegram_id == telegram_id, User.is_active.is_(True)).first()


def _get_untagged(db, household_id: uuid.UUID) -> list[Transaction]:
    return (
        db.query(Transaction)
        .filter(
            Transaction.household_id == household_id,
            Transaction.primary_tag.is_(None),
            Transaction.direction.in_(["expense", "income"]),
        )
        .order_by(Transaction.occurred_at.desc())
        .limit(50)
        .all()
    )


def _get_top_tags(db, household_id: uuid.UUID) -> list[str]:
    """Return top 4 most-used primary_tag values for this household."""
    from sqlalchemy import func
    rows = (
        db.query(Transaction.primary_tag, func.count(Transaction.id).label("cnt"))
        .filter(
            Transaction.household_id == household_id,
            Transaction.primary_tag.isnot(None),
        )
        .group_by(Transaction.primary_tag)
        .order_by(func.count(Transaction.id).desc())
        .limit(4)
        .all()
    )
    return [r[0] for r in rows]


def _build_inbox_keyboard(tx_id: str, top_tags: list[str]) -> InlineKeyboardMarkup:
    tag_buttons = [
        InlineKeyboardButton(text=f"#{t}", callback_data=f"{_CB_TAG}{tx_id}:{t}")
        for t in top_tags
    ]
    # Tags in rows of 2
    rows = []
    for i in range(0, len(tag_buttons), 2):
        rows.append(tag_buttons[i:i + 2])
    rows.append([
        InlineKeyboardButton(text="\u270f\ufe0f \u0421\u0432\u043e\u0439", callback_data=f"{_CB_CUSTOM}{tx_id}"),
        InlineKeyboardButton(text="\u23ed \u0421\u043a\u0438\u043f", callback_data=f"{_CB_SKIP}{tx_id}"),
        InlineKeyboardButton(text="\U0001f5d1 \u0423\u0434\u0430\u043b\u0438\u0442\u044c", callback_data=f"{_CB_DELETE}{tx_id}"),
    ])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _format_inbox_item(tx: Transaction, remaining: int) -> str:
    date_str = tx.occurred_at.strftime("%d.%m.%Y") if tx.occurred_at else "?"
    merchant = tx.merchant_raw or tx.description_raw or "без названия"
    return (
        f"🏷 Без тега ({remaining} осталось)\n\n"
        f"{tx.amount} {tx.currency.value} · {merchant}\n"
        f"{date_str}"
    )


async def send_inbox(message: Message, telegram_id: str, edit: bool = False) -> None:
    """Send the first untagged item. Used by /inbox command and month button."""
    with SessionLocal() as db:
        user = _find_user(db, telegram_id)
        if not user:
            await message.answer(
                "⚠️ Я не вижу твой профиль в этом household.\n\n"
                "Нужно привязать Telegram-аккаунт к пользователю HastleFam.\n"
                "Если это твой бот — проверь привязку в базе."
            )
            return

        untagged = _get_untagged(db, user.household_id)
        if not untagged:
            await message.answer("Всё в порядке. Записей без тега нет.")
            return

        top_tags = _get_top_tags(db, user.household_id)
        tx = untagged[0]
        remaining = len(untagged)
        text = _format_inbox_item(tx, remaining)
        keyboard = _build_inbox_keyboard(str(tx.id), top_tags)

    await message.answer(text, reply_markup=keyboard)


@router.message(Command("inbox"))
async def inbox_command(message: Message) -> None:
    await send_inbox(message, str(message.from_user.id) if message.from_user else "")


# ─── Quick tag ─────────────────────────────────────────────────────────────────

@router.callback_query(lambda c: c.data and c.data.startswith(_CB_TAG))
async def on_inbox_tag(callback: CallbackQuery) -> None:
    await callback.answer()
    # inbox:tag:{tx_id}:{tag}  — tx_id is UUID (36 chars), tag is after 4th colon segment
    payload = callback.data[len(_CB_TAG):]
    # UUID is 36 chars, then colon, then tag
    tx_id = payload[:36]
    tag = payload[37:] if len(payload) > 37 else ""

    if not tag:
        await callback.message.edit_text("⚠️ Не понял тег.", reply_markup=None)
        return

    _apply_tag(tx_id, tag)
    await _show_next(callback, str(callback.from_user.id))


# ─── Skip ──────────────────────────────────────────────────────────────────────

@router.callback_query(lambda c: c.data and c.data.startswith(_CB_SKIP))
async def on_inbox_skip(callback: CallbackQuery) -> None:
    await callback.answer()
    tx_id = callback.data[len(_CB_SKIP):]

    with SessionLocal() as db:
        user = _find_user(db, str(callback.from_user.id)) if callback.from_user else None
        if not user:
            await callback.message.edit_text("⚠️ Профиль не найден.", reply_markup=None)
            return
        untagged = _get_untagged(db, user.household_id)
        # Move to next item, skipping current tx_id
        remaining = [t for t in untagged if str(t.id) != tx_id]
        if not remaining:
            await callback.message.edit_text("Готово. Без тега не осталось.", reply_markup=None)
            return
        top_tags = _get_top_tags(db, user.household_id)
        tx = remaining[0]
        text = _format_inbox_item(tx, len(remaining))
        keyboard = _build_inbox_keyboard(str(tx.id), top_tags)

    await callback.message.edit_text(text, reply_markup=keyboard)


# ─── Delete ───────────────────────────────────────────────────────────────────

@router.callback_query(lambda c: c.data and c.data.startswith(_CB_DELETE))
async def on_inbox_delete(callback: CallbackQuery) -> None:
    await callback.answer()
    tx_id = callback.data[len(_CB_DELETE):]

    try:
        with SessionLocal() as db:
            tx = db.query(Transaction).filter(Transaction.id == uuid.UUID(tx_id)).first()
            if tx:
                db.delete(tx)
                db.commit()
    except Exception as e:
        log.error("inbox: failed to delete tx=%s: %s", tx_id, e)

    await _show_next(callback, str(callback.from_user.id))


# ─── Custom tag input ──────────────────────────────────────────────────────────

@router.callback_query(lambda c: c.data and c.data.startswith(_CB_CUSTOM))
async def on_inbox_custom(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    tx_id = callback.data[len(_CB_CUSTOM):]
    await state.set_state(InboxStates.waiting_custom_tag)
    await state.update_data(tx_id=tx_id)
    await callback.message.edit_text(
        "Введи тег одним словом (например: кафе, транспорт, продукты):\n\n/cancel — отменить",
        reply_markup=None,
    )


@router.message(StateFilter(InboxStates.waiting_custom_tag))
async def on_inbox_custom_input(message: Message, state: FSMContext) -> None:
    text = (message.text or "").strip().lstrip("#").lower()
    if not text:
        await message.answer("⚠️ Не понял тег. Напиши одно слово.")
        return

    data = await state.get_data()
    tx_id = data.get("tx_id", "")
    await state.clear()

    _apply_tag(tx_id, text)
    await message.answer(f"✅ #{text}")
    await send_inbox(message, str(message.from_user.id) if message.from_user else "")


# ─── Helpers ───────────────────────────────────────────────────────────────────

def _apply_tag(tx_id: str, tag: str) -> None:
    try:
        with SessionLocal() as db:
            tx = db.query(Transaction).filter(Transaction.id == uuid.UUID(tx_id)).first()
            if tx:
                tx.primary_tag = tag
                db.commit()
    except Exception as e:
        log.error("inbox: failed to apply tag tx=%s tag=%s: %s", tx_id, tag, e)


async def _show_next(callback: CallbackQuery, telegram_id: str) -> None:
    """After tagging, show next untagged item or completion message."""
    with SessionLocal() as db:
        user = _find_user(db, telegram_id)
        if not user:
            await callback.message.edit_text("✅ Готово.", reply_markup=None)
            return
        untagged = _get_untagged(db, user.household_id)
        if not untagged:
            await callback.message.edit_text("Готово. Без тега не осталось.", reply_markup=None)
            return
        top_tags = _get_top_tags(db, user.household_id)
        tx = untagged[0]
        text = _format_inbox_item(tx, len(untagged))
        keyboard = _build_inbox_keyboard(str(tx.id), top_tags)

    await callback.message.edit_text(text, reply_markup=keyboard)
