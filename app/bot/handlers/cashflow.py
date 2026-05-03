"""
cashflow.py — /cashflow command handler.

Shows a 60-day forward-looking financial picture:
  - Current account balances
  - Planned income (next 60 days)
  - Planned expenses (next 60 days)
  - Debts with due date in window (info only, not in projection formula)
  - Projected free balance at 30 and 60 days
"""
from __future__ import annotations

from decimal import Decimal

from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message

from app.application.services.finance_service import FinanceService
from app.infrastructure.db.models import User
from app.infrastructure.db.session import SessionLocal

router = Router()

_CUR_SYMBOL = {"RUB": "₽", "USD": "$", "EUR": "€", "PLN": "zł", "USDT": "₮"}


def _sym(currency: str) -> str:
    return _CUR_SYMBOL.get(currency, currency)


def _fmt(v: Decimal) -> str:
    return f"{v:,.0f}".replace(",", " ")


def _fmt_amount(amount: Decimal, currency: str) -> str:
    return f"{_fmt(amount)} {_sym(currency)}"


def _render_cashflow(data: dict) -> str:
    lines: list[str] = [f"💰 Кэшфлоу — {data['days']} дней", ""]

    # ── Balances ──────────────────────────────────────────────────────────
    account_items = data["account_items"]
    if account_items:
        balance_parts = []
        for a in account_items:
            if a["balance"] is not None:
                balance_parts.append(_fmt_amount(a["balance"], a["currency"]))
        if balance_parts:
            lines.append("Балансы: " + " · ".join(balance_parts))
        else:
            lines.append("Балансы: нет данных (введи /balances)")
    else:
        lines.append("Балансы: счета не настроены")
    lines.append("")

    # ── Planned income ────────────────────────────────────────────────────
    planned_income = data["planned_income"]
    if planned_income:
        lines.append("Планируется получить:")
        for item in planned_income:
            d = item["due_date"][5:]  # MM-DD → DD.MM
            day, mon = d.split("-")
            lines.append(f"• {day}.{mon} · {item['title'] or '—'} · +{_fmt_amount(Decimal(str(item['amount'])), item['currency'])}")
    else:
        lines.append("Планируется получить: ничего")
        lines.append("  Подсказка: +80000 зарплата 25-05")
    lines.append("")

    # ── Planned expenses ──────────────────────────────────────────────────
    planned_expenses = data["planned_expenses"]
    if planned_expenses:
        lines.append("Планируется потратить:")
        for item in planned_expenses:
            d = item["due_date"][5:]
            day, mon = d.split("-")
            lines.append(f"• {day}.{mon} · {item['title'] or '—'} · {_fmt_amount(Decimal(str(item['amount'])), item['currency'])}")
    else:
        lines.append("Планируется потратить: ничего")
        lines.append("  Подсказка: 3000 аренда 25-05 #жильё")
    lines.append("")

    # ── Debts due ─────────────────────────────────────────────────────────
    debts_due = data["debts_due"]
    if debts_due:
        lines.append("Долги к выплате:")
        for d in debts_due:
            dd = d["due_date"][5:]
            day, mon = dd.split("-")
            direction_hint = "ты должен" if d["direction"] == "i_owe" else "тебе должны"
            lines.append(f"• до {day}.{mon} · {d['counterparty']} · {_fmt_amount(d['amount'], d['currency'])} ({direction_hint})")
        lines.append("")

    # ── Projection ────────────────────────────────────────────────────────
    fx_note = " ⚠️ FX частично недоступен, конвертация приблизительная" if data["fx_unavailable"] else ""
    lines.append(f"Прогноз свободного остатка:{fx_note}")
    free_30 = data["free_30"]
    free_60 = data["free_60"]
    sign_30 = "" if free_30 < 0 else "~"
    sign_60 = "" if free_60 < 0 else "~"
    lines.append(f"• Через 30 дней: {sign_30}{_fmt(free_30)} ₽")
    lines.append(f"• Через 60 дней: {sign_60}{_fmt(free_60)} ₽")

    if data["fx_unavailable"]:
        lines.append("")
        lines.append("(Суммы без курса оценены как 0 ₽)")

    return "\n".join(lines)


@router.message(Command("cashflow"))
async def cashflow_command(message: Message) -> None:
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

        data = FinanceService(db).cashflow_projection(str(user.household_id), days=60)

    text = _render_cashflow(data)
    await message.answer(text)
