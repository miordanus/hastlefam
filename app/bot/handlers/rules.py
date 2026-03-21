"""/rules command — manage auto-categorization rules (merchant → tag).

Commands:
  /rules              — list all active rules
  /rules кофейня тег  — create/update rule: "кофейня" → #тег
  /rules удалить кофейня — delete rule for "кофейня"
"""
from __future__ import annotations

import logging

from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message

from app.application.services.autocat_service import create_manual_rule, delete_rule, list_rules
from app.infrastructure.db.models import User
from app.infrastructure.db.session import SessionLocal

router = Router()
log = logging.getLogger(__name__)


def _find_user(db, telegram_id: str):
    return db.query(User).filter(User.telegram_id == telegram_id, User.is_active.is_(True)).first()


@router.message(Command("rules"))
async def rules_command(message: Message):
    text = (message.text or "").replace("/rules", "", 1).strip()

    with SessionLocal() as db:
        user = _find_user(db, str(message.from_user.id)) if message.from_user else None
        if not user:
            await message.answer("⚠️ Профиль не найден.")
            return

        hid = user.household_id

        # /rules удалить <merchant>
        if text.startswith("удалить ") or text.startswith("delete "):
            merchant = text.split(maxsplit=1)[1].strip()
            ok = delete_rule(db, hid, merchant)
            if ok:
                await message.answer(f"✅ Правило для «{merchant}» удалено.")
            else:
                await message.answer(f"⚠️ Правило для «{merchant}» не найдено.")
            return

        # /rules <merchant> <tag> — create rule
        parts = text.split()
        if len(parts) >= 2:
            merchant = parts[0]
            tag = parts[1].lstrip("#")
            rule = create_manual_rule(db, hid, merchant, tag)
            await message.answer(f"✅ Правило: «{rule.merchant_pattern}» → #{rule.tag}")
            return

        # /rules — list all
        rules = list_rules(db, hid)
        if not rules:
            await message.answer(
                "📋 Правил автокатегоризации пока нет.\n\n"
                "Они создаются автоматически, когда ты 3+ раз тегаешь одного мерчанта одинаково.\n\n"
                "Или добавь вручную:\n"
                "`/rules кофейня кафе`"
            )
            return

        lines = ["📋 Правила автокатегоризации:\n"]
        for r in rules:
            src = "🤖" if r.source == "auto" else "✏️"
            lines.append(f"{src} {r.merchant_pattern} → #{r.tag}  ({r.hit_count}×)")
        lines.append(f"\nВсего: {len(rules)}")
        lines.append("\nУправление:")
        lines.append("`/rules мерчант тег` — добавить")
        lines.append("`/rules удалить мерчант` — удалить")
        await message.answer("\n".join(lines))
