"""/budgets — Monthly category budget overview with limit management.

Shows per-category: actual spent, planned, limit, remaining, status.
Inline buttons: ✏️ Лимит (FSM), 📋 Транзакции (last 5).
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
from app.infrastructure.db.models import CategoryBudget, FinanceCategory, Transaction, User
from app.infrastructure.db.session import SessionLocal

router = Router()
log = logging.getLogger(__name__)

_CB_SET_LIMIT = "budget_set_limit:"
_CB_TRANSACTIONS = "budget_txns:"


class BudgetStates(StatesGroup):
    waiting_category = State()
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
        lines.append("Лимиты не заданы. Нажми ✏️ Новый лимит чтобы добавить.")
    else:
        for s in statuses:
            emoji = _status_emoji(s["status"])
            name = s["category_name"]
            actual = _fmt(s["actual_spent"])
            limit = _fmt(s["limit_amount"])
            cur = s["currency"]
            planned = s["planned_amount"]
            remaining = s["remaining_after_planned"]

            if planned > 0:
                line = (
                    f"{emoji} <b>{name}</b>  "
                    f"{actual} + {_fmt(planned)} план / {limit} {cur}  "
                    f"осталось {_fmt(remaining)} {cur}"
                )
            else:
                sign = "+" if remaining >= 0 else ""
                line = (
                    f"{emoji} <b>{name}</b>  "
                    f"{actual} / {limit} {cur}  "
                    f"осталось {sign}{_fmt(remaining)} {cur}"
                )
            lines.append(line)

    return "\n".join(lines)


def _build_budgets_keyboard(statuses: list, month_key: str) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []

    for s in statuses:
        budget_id = s["budget_id"]
        name = s["category_name"]
        row = [
            InlineKeyboardButton(text=f"✏️ {name}: лимит", callback_data=f"{_CB_SET_LIMIT}{budget_id}"),
            InlineKeyboardButton(text="📋 Транзакции", callback_data=f"{_CB_TRANSACTIONS}{budget_id}:{month_key}"),
        ]
        rows.append(row)

    rows.append([InlineKeyboardButton(text="➕ Новый лимит", callback_data=f"budget_new:{month_key}")])
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
    await state.update_data(budget_id=budget_id, category_id=None, month_key=None, household_id=None)
    await call.message.answer("Введи новый лимит (число в RUB):")
    await call.answer()


# ─── New limit flow ───────────────────────────────────────────────────────────

@router.callback_query(F.data.startswith("budget_new:"))
async def cb_new_budget(call: CallbackQuery, state: FSMContext):
    month_key = call.data[len("budget_new:"):]
    await state.set_state(BudgetStates.waiting_category)
    await state.update_data(month_key=month_key)

    with SessionLocal() as db:
        user = _find_user(db, str(call.from_user.id)) if call.from_user else None
        if not user:
            await call.message.answer("⚠️ Профиль не найден.")
            await call.answer()
            return
        cats = (
            db.query(FinanceCategory)
            .filter(
                (FinanceCategory.household_id == user.household_id) |
                (FinanceCategory.household_id.is_(None))
            )
            .order_by(FinanceCategory.name)
            .limit(20)
            .all()
        )
        await state.update_data(household_id=str(user.household_id))

    if not cats:
        await call.message.answer("Категории не найдены. Добавь транзакции с тегами.")
        await state.clear()
        await call.answer()
        return

    buttons = [
        [InlineKeyboardButton(text=c.name, callback_data=f"budget_cat:{c.id}")]
        for c in cats
    ]
    kb = InlineKeyboardMarkup(inline_keyboard=buttons)
    await call.message.answer("Выбери категорию для бюджета:", reply_markup=kb)
    await call.answer()


@router.callback_query(F.data.startswith("budget_cat:"))
async def cb_budget_category(call: CallbackQuery, state: FSMContext):
    cat_id = call.data[len("budget_cat:"):]
    await state.update_data(category_id=cat_id)
    await state.set_state(BudgetStates.waiting_limit)
    await call.message.answer("Введи лимит для этой категории (число в RUB):")
    await call.answer()


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
    category_id = data.get("category_id")
    month_key = data.get("month_key")
    household_id = data.get("household_id")
    await state.clear()

    with SessionLocal() as db:
        if budget_id:
            # Update existing
            budget = db.get(CategoryBudget, uuid.UUID(budget_id))
            if budget:
                budget.limit_amount = new_limit
                db.commit()
            await message.answer(f"✅ Лимит обновлён: {_fmt(new_limit)} RUB")
        elif category_id and month_key and household_id:
            # Create new
            existing = (
                db.query(CategoryBudget)
                .filter(
                    CategoryBudget.household_id == uuid.UUID(household_id),
                    CategoryBudget.month_key == month_key,
                    CategoryBudget.category_id == uuid.UUID(category_id),
                )
                .first()
            )
            if existing:
                existing.limit_amount = new_limit
            else:
                db.add(CategoryBudget(
                    household_id=uuid.UUID(household_id),
                    month_key=month_key,
                    category_id=uuid.UUID(category_id),
                    limit_amount=new_limit,
                    currency="RUB",
                ))
            db.commit()
            await message.answer(f"✅ Бюджет создан: {_fmt(new_limit)} RUB")
        else:
            await message.answer("⚠️ Не удалось сохранить. Попробуй снова.")


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

        budget = db.get(CategoryBudget, uuid.UUID(budget_id))
        if not budget:
            await call.answer("Бюджет не найден.")
            return

        cat_name = "Без категории"
        if budget.category_id:
            cat = db.get(FinanceCategory, budget.category_id)
            if cat:
                cat_name = cat.name

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
                Transaction.primary_tag == cat_name.lower(),
                Transaction.is_planned == False,  # noqa: E712
            )
            .order_by(Transaction.occurred_at.desc())
            .limit(5)
            .all()
        )

    if not txns:
        await call.message.answer(f"Нет транзакций в категории «{cat_name}».")
        await call.answer()
        return

    lines = [f"<b>Последние транзакции — {cat_name}:</b>"]
    for tx in txns:
        d = tx.occurred_at.strftime("%d.%m")
        cur = tx.currency.value if tx.currency else "RUB"
        merchant = tx.merchant_raw or "—"
        lines.append(f"• {d} | {merchant} | {_fmt(tx.amount)} {cur}")

    await call.message.answer("\n".join(lines), parse_mode="HTML")
    await call.answer()
