"""forecast.py — /forecast command: 6-week planned payment summary grouped by week."""
from __future__ import annotations

from decimal import Decimal

from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message

from app.application.services.finance_service import FinanceService
from app.infrastructure.db.session import SessionLocal

router = Router()

_NBSP = " "  # narrow no-break space for thousands separator


def _fmt(amount) -> str:
    val = int(Decimal(str(amount)).to_integral_value())
    return f"{val:,}".replace(",", _NBSP)


def _find_user(db, telegram_id: str):
    from app.infrastructure.db.models import User
    return db.query(User).filter(User.telegram_id == telegram_id, User.is_active.is_(True)).first()


@router.message(Command("forecast"))
async def forecast_command(message: Message) -> None:
    telegram_id = str(message.from_user.id) if message.from_user else ""
    with SessionLocal() as db:
        user = _find_user(db, telegram_id)
        if not user:
            await message.answer(
                "⚠️ Профиль не найден.\n\nНужно привязать Telegram к пользователю HastleFam."
            )
            return
        data = FinanceService(db).forecast_by_week(str(user.household_id))

    overdue = data.get("overdue", [])
    weeks = data.get("weeks", [])

    if not overdue and not weeks:
        await message.answer("🗓 Нет запланированных платежей в ближайшие 6 недель.")
        return

    lines: list[str] = ["📆 *Прогноз на 6 недель*\n"]

    if overdue:
        lines.append("⚠️ *Просроченные*")
        for item in overdue:
            icon = "💰" if item.get("direction") == "income" else "💸"
            tag = f" #{item['primary_tag']}" if item.get("primary_tag") else ""
            cur = item.get("currency", "RUB")
            title = item.get("merchant_raw") or item.get("title", "?")
            lines.append(f"  {icon} {_fmt(item['amount'])} {cur} · {title}{tag}")
        lines.append("")

    for week in weeks:
        exp, inc = week["total_expense"], week["total_income"]
        totals_parts = []
        if exp:
            totals_parts.append(f" −{_fmt(exp)} ₽")
        if inc:
            totals_parts.append(f" +{_fmt(inc)} ₽")
        totals = "".join(totals_parts)
        lines.append(f"📅 *{week['week_label']}*{totals}")
        for item in week["items"]:
            icon = "💰" if item.get("direction") == "income" else "💸"
            tag = f" #{item['primary_tag']}" if item.get("primary_tag") else ""
            cur = item.get("currency", "RUB")
            lines.append(f"  {icon} {_fmt(item['amount'])} {cur} · {item.get('title', '?')}{tag}")
        lines.append("")

    await message.answer("\n".join(lines).rstrip(), parse_mode="Markdown")
