"""
review.py — /review command handler.

Assembles one unified weekly review screen from existing service calls.
No new queries, no new logic. All sections degrade gracefully when empty.
"""
from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

from aiogram import Router
from aiogram.filters import Command
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, Message

from app.application.services.finance_service import FinanceService
from app.domain.enums import TransactionDirection
from app.infrastructure.db.models import Debt, User
from app.infrastructure.db.session import SessionLocal

router = Router()

_CUR_SYMBOL = {"RUB": "₽", "USD": "$", "EUR": "€", "PLN": "zł", "USDT": "₮"}
_MONTH_RU = {
    1: "Январь", 2: "Февраль", 3: "Март", 4: "Апрель",
    5: "Май", 6: "Июнь", 7: "Июль", 8: "Август",
    9: "Сентябрь", 10: "Октябрь", 11: "Ноябрь", 12: "Декабрь",
}


def _sym(c: str) -> str:
    return _CUR_SYMBOL.get(c, c)


def _fmt(v: Decimal) -> str:
    return f"{v:,.0f}".replace(",", " ")


def _fmt_cur(by_currency: dict[str, Decimal]) -> str:
    if not by_currency:
        return "0 ₽"
    return " | ".join(f"{_fmt(v)} {_sym(c)}" for c, v in by_currency.items())


def _build_review_keyboard(untagged: int) -> InlineKeyboardMarkup:
    rows = []
    if untagged > 0:
        rows.append([InlineKeyboardButton(
            text=f"🏷 Разобрать ({untagged})",
            callback_data="month:open_inbox",
        )])
    rows.append([InlineKeyboardButton(
        text="📅 Добавить план",
        callback_data="month:open_upcoming",
    )])
    return InlineKeyboardMarkup(inline_keyboard=rows)


@router.message(Command("review"))
async def review_command(message: Message) -> None:
    with SessionLocal() as db:
        user = (
            db.query(User)
            .filter(
                User.telegram_id == str(message.from_user.id),
                User.is_active.is_(True),
            )
            .first()
            if message.from_user
            else None
        )
        if not user:
            await message.answer(
                "⚠️ Я не вижу твой профиль в этом household.\n"
                "Нужно привязать Telegram-аккаунт к пользователю HastleFam."
            )
            return

        hid = str(user.household_id)
        today = datetime.now(timezone.utc).date()
        svc = FinanceService(db)

        # Gather all data in one session
        balances = svc.balance_summary(hid)
        month_data = svc.month_summary(hid, for_date=today)
        projection = svc.cashflow_projection(hid, days=30)

        budget_statuses: list = []
        try:
            from app.application.services.budget_service import get_budget_status
            month_key = today.strftime("%Y-%m")
            budget_statuses = get_budget_status(hid, month_key, db) or []
        except Exception:
            pass

        open_debts = (
            db.query(Debt)
            .filter(
                Debt.household_id == user.household_id,
                Debt.settled_at.is_(None),
            )
            .all()
        )

    # ── Format output ─────────────────────────────────────────────────────
    lines: list[str] = [
        f"<b>📋 Обзор — {today.strftime('%d.%m.%Y')}</b>",
        "",
    ]

    # Balances
    accs = [a for a in balances["accounts"] if a["current_balance"] is not None]
    if accs:
        bal_parts = [f"{_fmt(a['current_balance'])} {_sym(a['currency'])}" for a in accs]
        lines.append(f"💰 Балансы: {' · '.join(bal_parts)}")
    else:
        lines.append("💰 Балансы: нет данных — /balances")
    lines.append("")

    # MTD
    month_label = _MONTH_RU[today.month]
    spend = month_data["spend_by_currency"]
    income = month_data["income_by_currency"]
    untagged = month_data.get("untagged_count", 0)
    lines.append(f"<b>{month_label} — факт:</b>")
    lines.append(f"📤 Расходы: {_fmt_cur(spend)}")
    lines.append(f"📥 Доходы: {_fmt_cur(income)}")
    lines.append("")

    # Planned (next 30 days)
    planned_income = projection["planned_income"]
    planned_expenses = projection["planned_expenses"]
    lines.append("<b>Ближайшие 30 дней:</b>")
    if planned_income:
        for item in planned_income[:3]:
            d = item["due_date"][5:]
            day, mon = d.split("-")
            lines.append(f"  💰 {day}.{mon} · {item['title'] or '—'} · +{_fmt(Decimal(str(item['amount'])))} {_sym(item['currency'])}")
    if planned_expenses:
        for item in planned_expenses[:5]:
            d = item["due_date"][5:]
            day, mon = d.split("-")
            lines.append(f"  📅 {day}.{mon} · {item['title'] or '—'} · {_fmt(Decimal(str(item['amount'])))} {_sym(item['currency'])}")
    if not planned_income and not planned_expenses:
        lines.append("  Ничего не запланировано")
    lines.append("")

    # Projection
    free_30 = projection["free_30"]
    fx_note = " (FX приблизит.)" if projection["fx_unavailable"] else ""
    lines.append(f"🔮 Прогноз через 30 дней: ~{_fmt(free_30)} ₽{fx_note}")
    lines.append("")

    # Risk section — only actionable items
    risk_lines: list[str] = []
    over_budget = [s for s in budget_statuses if s["status"] == "over_budget"]
    at_risk = [s for s in budget_statuses if s["status"] == "at_risk"]
    for s in over_budget:
        overage = s["actual_spent"] - s["limit_amount"]
        risk_lines.append(f"🔴 {s['category_name']}: перерасход {_fmt(overage)} {_sym(s['currency'])}")
    for s in at_risk[:2]:
        risk_lines.append(f"⚠️ {s['category_name']}: риск ({_fmt(s['remaining_after_planned'])} осталось)")
    if open_debts:
        risk_lines.append(f"💸 Долгов открытых: {len(open_debts)}")
    if untagged > 0:
        risk_lines.append(f"🏷 Без тега: {untagged}")
    if risk_lines:
        lines.append("<b>⚠️ Требует внимания:</b>")
        lines += risk_lines
    else:
        lines.append("✅ Нет срочных вопросов")

    text = "\n".join(lines)
    keyboard = _build_review_keyboard(untagged)
    await message.answer(text, reply_markup=keyboard, parse_mode="HTML")
