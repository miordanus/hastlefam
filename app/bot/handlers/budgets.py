"""/budgets — Monthly tag budget overview with limit management.

Shows per-tag: actual spent, planned, limit (+rollover), remaining, status.
Inline buttons: ✏️ Лимит (FSM), 📋 Транзакции (last 5), ↩️ Переносить (toggle rollover).
"""
from __future__ import annotations

import logging
import uuid
from datetime import date
from decimal import Decimal

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from app.application.services.budget_service import _fmt, get_budget_status
from app.infrastructure.db.models import TagBudget, Transaction, User
from app.infrastructure.db.session import SessionLocal

router = Router()
log = logging.getLogger(__name__)

_CB_SET_LIMIT = "budget_set_limit:"
_CB_TRANSACTIONS = "budget_txns:"
_CB_TOGGLE_ROLLOVER = "budget_rollover:"


class BudgetStates(StatesGroup):
    waiting_tag = State()
    waiting_limit = State()


def _find_user(db, telegram_id: str):
    return db.query(User).filter(User.telegram_id == telegram_id, User.is_active.is_(True)).first()


def _status_emoji(status: str) -> str:
    return {"ok": "✅", "at_risk": "⚠️", "over_budget": "🔴"}.get(status, "")


def _build_budgets_text(statuses: list, month_key: str) -> str:
    month_names = {
        "01": "Январь", "02": "Февраль", "03": "Март", "04": "Апрель",
        "05": "Май", "06": "Июнь", "07": "Июль", "08": "Август",
        "09": "Сентябрь", "10": "Октябрь", "11": "Ноябрь", "12": "Декабрь",
    }
    year, mo = month_key[:4], month_key[5:7]
    month_name = month_names.get(mo, mo)
    lines = [f"📊 <b>Бюджеты — {month_name} {year}</b>\n"]

    if not statuses:
        lines.append("Лимиты не заданы. Нажми ➕ Добавить чтобы задать лимит по тегу.")
    else:
        for s in statuses:
            emoji = _status_emoji(s["status"])
            tag = s["tag"]
            actual = _fmt(s["actual_spent"])
            limit = _fmt(s["limit_amount"])
            cur = s["currency"]
            planned = s["planned_amount"]
            remaining = s["remaining_after_planned"]
            rollover = s.get("rollover_amount", Decimal("0"))

            rollover_suffix = ""
            if rollover > 0:
                rollover_suffix = f" (+{_fmt(rollover)} перенос)"

            if planned > 0:
                line = (
                    f"{emoji} <b>{tag}</b>  "
                    f"{actual} + {_fmt(planned)} план / {limit}{rollover_suffix} {cur}  "
                    f"осталось {_fmt(remaining)} {cur}"
                )
            else:
                sign = "+" if remaining >= 0 else ""
                line = (
                    f"{emoji} <b>{tag}</b>  "
                    f"{actual} / {limit}{rollover_suffix} {cur}  "
                    f"осталось {sign}{_fmt(remaining)} {cur}"
                )
            lines.append(line)

    return "\n".join(lines)


def _build_budgets_keyboard(statuses: list, month_key: str) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []

    for s in statuses:
        budget_id = s["budget_id"]
        tag = s["tag"]
        rollover_enabled = s.get("rollover_enabled", False)
        rollover_label = "↩️ Не переносить" if rollover_enabled else "↩️ Переносить"

        rows.append([
            InlineKeyboardButton(text=f"✏️ {tag}: лимит", callback_data=f"{_CB_SET_LIMIT}{budget_id}"),
            InlineKeyboardButton(text="📋 Транзакции", callback_data=f"{_CB_TRANSACTIONS}{budget_id}:{month_key}"),
        ])
        rows.append([
            InlineKeyboardButton(text=rollover_label, callback_data=f"{_CB_TOGGLE_ROLLOVER}{budget_id}:{month_key}"),
        ])

    rows.append([InlineKeyboardButton(text="➕ Добавить", callback_data=f"budget_new:{month_key}")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


async def send_budgets(message: Message, telegram_id: str):
    """Shared helper — telegram_id passed explicitly (safe from callbacks)."""
    with SessionLocal() as db:
        user = _find_user(db, telegram_id)
        if not user:
            await message.answer("⚠️ Профиль не найден.")
            return

        month_key = date.today().strftime("%Y-%m")
        statuses = get_budget_status(str(user.household_id), month_key, db)

    text = _build_budgets_text(statuses, month_key)
    kb = _build_budgets_keyboard(statuses, month_key)
    await message.answer(text, reply_markup=kb, parse_mode="HTML")


@router.message(Command("budgets"))
async def cmd_budgets(message: Message):
    await send_budgets(message, str(message.from_user.id) if message.from_user else "")


# ─── Set limit flow ───────────────────────────────────────────────────────────

@router.callback_query(F.data.startswith(_CB_SET_LIMIT))
async def cb_set_limit(call: CallbackQuery, state: FSMContext):
    budget_id = call.data[len(_CB_SET_LIMIT):]
    await state.set_state(BudgetStates.waiting_limit)
    await state.update_data(budget_id=budget_id, tag=None, month_key=None, household_id=None)
    await call.message.answer("Введи новый лимит (число в RUB):")
    await call.answer()


# ─── New budget flow ──────────────────────────────────────────────────────────

@router.callback_query(F.data.startswith("budget_new:"))
async def cb_new_budget(call: CallbackQuery, state: FSMContext):
    month_key = call.data[len("budget_new:"):]

    with SessionLocal() as db:
        user = _find_user(db, str(call.from_user.id)) if call.from_user else None
        if not user:
            await call.message.answer("⚠️ Профиль не найден.")
            await call.answer()
            return
        await state.update_data(month_key=month_key, household_id=str(user.household_id))

    await state.set_state(BudgetStates.waiting_tag)
    await call.message.answer(
        "Введи тег для бюджета (например: <code>еда</code> или <code>транспорт</code>).\n"
        "Тег будет приведён к нижнему регистру.",
        parse_mode="HTML",
    )
    await call.answer()


@router.message(BudgetStates.waiting_tag)
async def recv_tag(message: Message, state: FSMContext):
    tag = (message.text or "").strip().lstrip('#').lower()
    if not tag or len(tag) < 1:
        await message.answer("Введи непустой тег. Попробуй снова или /cancel.")
        return
    await state.update_data(tag=tag)
    await state.set_state(BudgetStates.waiting_limit)
    await message.answer(f"Тег: <b>{tag}</b>\nТеперь введи лимит (число в RUB):", parse_mode="HTML")


@router.message(BudgetStates.waiting_limit)
async def recv_limit(message: Message, state: FSMContext):
    """Handles both update-existing and create-new limit flows."""
    text = (message.text or "").strip().replace(",", ".")
    try:
        new_limit = Decimal(text)
        if new_limit <= 0:
            raise ValueError
    except Exception:
        await message.answer("Пожалуйста, введи положительное число. Попробуй снова или /cancel.")
        return

    data = await state.get_data()
    budget_id = data.get("budget_id")
    tag = data.get("tag")
    month_key = data.get("month_key")
    household_id = data.get("household_id")
    await state.clear()

    with SessionLocal() as db:
        if budget_id:
            # Update existing TagBudget
            budget = db.get(TagBudget, uuid.UUID(budget_id))
            if budget:
                budget.limit_amount = new_limit
                db.commit()
            await message.answer(f"✅ Лимит обновлён: {_fmt(new_limit)} RUB")
        elif tag and month_key and household_id:
            # Create new TagBudget
            existing = (
                db.query(TagBudget)
                .filter(
                    TagBudget.household_id == uuid.UUID(household_id),
                    TagBudget.month_key == month_key,
                    TagBudget.tag == tag,
                )
                .first()
            )
            if existing:
                existing.limit_amount = new_limit
            else:
                db.add(TagBudget(
                    household_id=uuid.UUID(household_id),
                    month_key=month_key,
                    tag=tag,
                    limit_amount=new_limit,
                    currency="RUB",
                ))
            db.commit()
            await message.answer(f"✅ Бюджет создан: <b>{tag}</b> → {_fmt(new_limit)} RUB", parse_mode="HTML")
        else:
            await message.answer("⚠️ Не удалось сохранить. Попробуй снова.")


# ─── Toggle rollover ──────────────────────────────────────────────────────────

@router.callback_query(F.data.startswith(_CB_TOGGLE_ROLLOVER))
async def cb_toggle_rollover(call: CallbackQuery):
    parts = call.data[len(_CB_TOGGLE_ROLLOVER):].split(":")
    budget_id, month_key = parts[0], parts[1]

    with SessionLocal() as db:
        budget = db.get(TagBudget, uuid.UUID(budget_id))
        if not budget:
            await call.answer("Бюджет не найден.")
            return
        budget.rollover_enabled = not budget.rollover_enabled
        db.commit()
        household_id = str(budget.household_id)

    # Re-render budgets
    with SessionLocal() as db:
        statuses = get_budget_status(household_id, month_key, db)

    text = _build_budgets_text(statuses, month_key)
    kb = _build_budgets_keyboard(statuses, month_key)
    await call.message.edit_text(text, reply_markup=kb, parse_mode="HTML")
    await call.answer()


# ─── Transactions list ────────────────────────────────────────────────────────

@router.callback_query(F.data.startswith(_CB_TRANSACTIONS))
async def cb_budget_transactions(call: CallbackQuery):
    parts = call.data[len(_CB_TRANSACTIONS):].split(":")
    budget_id, month_key = parts[0], parts[1]

    with SessionLocal() as db:
        user = _find_user(db, str(call.from_user.id)) if call.from_user else None
        if not user:
            await call.answer("Профиль не найден.")
            return

        budget = db.get(TagBudget, uuid.UUID(budget_id))
        if not budget:
            await call.answer("Бюджет не найден.")
            return

        tag = budget.tag

        try:
            year, month = int(month_key[:4]), int(month_key[5:7])
        except ValueError:
            await call.answer("Ошибка формата месяца.")
            return

        from datetime import datetime, timezone
        import calendar
        month_start = datetime(year, month, 1, tzinfo=timezone.utc)
        last_day = calendar.monthrange(year, month)[1]
        month_end = datetime(year, month, last_day, 23, 59, 59, tzinfo=timezone.utc)

        txns = (
            db.query(Transaction)
            .filter(
                Transaction.household_id == user.household_id,
                Transaction.occurred_at >= month_start,
                Transaction.occurred_at <= month_end,
                Transaction.primary_tag == tag,
                Transaction.is_planned == False,  # noqa: E712
            )
            .order_by(Transaction.occurred_at.desc())
            .limit(5)
            .all()
        )

    if not txns:
        await call.message.answer(f"Нет транзакций по тегу «{tag}».")
        await call.answer()
        return

    lines = [f"<b>Последние транзакции — {tag}:</b>"]
    for tx in txns:
        d = tx.occurred_at.strftime("%d.%m")
        cur = tx.currency.value if tx.currency else "RUB"
        merchant = tx.merchant_raw or "—"
        lines.append(f"• {d} | {merchant} | {_fmt(tx.amount)} {cur}")

    await call.message.answer("\n".join(lines), parse_mode="HTML")
    await call.answer()
