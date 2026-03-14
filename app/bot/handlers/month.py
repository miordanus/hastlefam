"""
month.py — /month command handler.
Renders a human-readable monthly summary per copy pack.
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


def _find_user(db, telegram_id: str):
    return db.query(User).filter(User.telegram_id == telegram_id, User.is_active.is_(True)).first()


def _format_currency_block(by_currency: dict[str, Decimal]) -> str:
    if not by_currency:
        return "• 0 RUB"
    return "\n".join(f"• {v} {cur}" for cur, v in by_currency.items())


@router.message(Command("month"))
async def month_command(message: Message):
    with SessionLocal() as db:
        user = _find_user(db, str(message.from_user.id)) if message.from_user else None
        if not user:
            await message.answer(
                "⚠️ Я не вижу твой профиль в этом household.\n\n"
                "Нужно привязать Telegram-аккаунт к пользователю HastleFam.\n"
                "Если это твой бот — проверь привязку в базе."
            )
            return
        summary = FinanceService(db).month_summary(str(user.household_id))

    spend_block = _format_currency_block(summary["spend_by_currency"])
    income_block = _format_currency_block(summary["income_by_currency"])

    if not summary["income_by_currency"]:
        income_block = "• Доходов за этот месяц пока нет."

    # Planned till month end
    planned = summary["upcoming_until_month_end"]
    if planned:
        planned_block = "\n".join(
            f"• {x['due_date']} · {x['title']} · {x['amount']} {x['currency']}"
            for x in planned[:5]
        )
    else:
        planned_block = "• Ничего не запланировано"

    # Top primary tags
    tags = summary["top_tags"]
    if tags:
        tags_block = "\n".join(f"• {x['tag']}: {x['amount']}" for x in tags[:5])
    else:
        tags_block = "• Пока нет категорий в сводке."

    # Attention block
    attention_lines = []
    untagged = summary.get("untagged_count", 0)
    if untagged:
        attention_lines.append(f"• {untagged} записей без категории")
    if not attention_lines:
        attention_lines.append("• Всё чисто")
    attention_block = "\n".join(attention_lines)

    lines = [
        "📊 Месяц на сейчас",
        "",
        f"💸 Потрачено:\n{spend_block}",
        "",
        f"💰 Доход:\n{income_block}",
        "",
        f"🗓 Запланировано до конца месяца:\n{planned_block}",
        "",
        f"🏷 Топ-категории:\n{tags_block}",
        "",
        f"⚠️ Требует внимания:\n{attention_block}",
    ]
    await message.answer("\n".join(lines))
