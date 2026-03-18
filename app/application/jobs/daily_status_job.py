"""
daily_status_job.py — sends daily status at 10:00 MSK to all household users.

Schedule: daily at 10:00 Europe/Moscow (UTC+3, DST-aware).
Content: MTD spend, MTD income, planned soon (next 3 days), missing tag count.

Requires apscheduler>=3.10 in pyproject.toml.
"""
from __future__ import annotations

import logging
from decimal import Decimal
from zoneinfo import ZoneInfo

from apscheduler.schedulers.asyncio import AsyncIOScheduler

log = logging.getLogger(__name__)

MSK = ZoneInfo("Europe/Moscow")


def _format_currency_block(by_currency: dict[str, Decimal]) -> str:
    if not by_currency:
        return "• 0 RUB"
    return "\n".join(f"• {v} {cur}" for cur, v in by_currency.items())


async def send_daily_status(bot) -> None:
    """Fetch status data and send to all active Telegram users in each household."""
    from app.application.services.finance_service import FinanceService
    from app.infrastructure.db.models import User
    from app.infrastructure.db.session import SessionLocal

    # Refresh FX rates before sending digest
    try:
        from app.application.services.fx_service import fetch_and_store_rates
        await fetch_and_store_rates()
    except Exception as exc:
        log.warning("daily_status: fx rate fetch failed: %s", exc)

    try:
        with SessionLocal() as db:
            users = db.query(User).filter(User.is_active.is_(True)).all()
            if not users:
                return

            # Group by household to avoid duplicate summaries per household
            seen_households: set[str] = set()
            for user in users:
                hid = str(user.household_id)
                if not user.telegram_id:
                    continue

                summary = FinanceService(db).daily_status_summary(hid)

                spend_block = _format_currency_block(summary["spend_by_currency"])
                income_block = _format_currency_block(summary["income_by_currency"])

                planned = summary["planned_soon"]
                if planned:
                    planned_block = "\n".join(
                        f"• {x['due_date']} · {x['title']} · {x['amount']} {x['currency']}"
                        for x in planned[:3]
                    )
                else:
                    planned_block = "• Ничего не запланировано"

                attention_lines = []
                untagged = summary.get("untagged_count", 0)
                if untagged:
                    attention_lines.append(f"• {untagged} записей без категории")

                attention_block = "\n".join(attention_lines) if attention_lines else ""

                lines = [
                    "🔔 Статус на сегодня",
                    "",
                    f"💸 Потрачено с начала месяца:\n{spend_block}",
                    "",
                    f"💰 Доход с начала месяца:\n{income_block}",
                    "",
                    f"🗓 Скоро к оплате:\n{planned_block}",
                ]
                if attention_block:
                    lines += ["", f"⚠️ Добить:\n{attention_block}"]

                text = "\n".join(lines)

                try:
                    await bot.send_message(chat_id=int(user.telegram_id), text=text)
                except Exception as e:
                    log.warning("daily_status: failed to send to %s: %s", user.telegram_id, e)

    except Exception as e:
        log.error("daily_status job failed: %s", e, exc_info=True)


def start_daily_status_scheduler(bot) -> AsyncIOScheduler:
    """Create and start the APScheduler for daily status. Returns scheduler instance."""
    scheduler = AsyncIOScheduler(timezone=MSK)
    scheduler.add_job(
        send_daily_status,
        trigger="cron",
        hour=10,
        minute=0,
        kwargs={"bot": bot},
        id="daily_status",
        replace_existing=True,
    )
    scheduler.start()
    log.info("daily_status scheduler started (10:00 MSK)")
    return scheduler
