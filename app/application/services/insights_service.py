"""insights_service.py — OpenAI-powered monthly finance insights.

Collects monthly data, builds a prompt, and calls gpt-4.1-mini.
Degrades gracefully: returns error string if OpenAI is unavailable.
"""
from __future__ import annotations

import logging
from datetime import date
from decimal import Decimal

from sqlalchemy.orm import Session

log = logging.getLogger(__name__)

_SYSTEM_PROMPT = (
    "Ты финансовый советник семейного бюджета. "
    "Отвечай на русском, кратко, по делу. "
    "Дай 3-4 вывода и 1-2 рекомендации."
)


def _build_user_prompt(
    year: int,
    month: int,
    spend_by_currency: dict,
    income_by_currency: dict,
    top_tags: list,
    prev_top_tags: list,
) -> str:
    month_names = {
        1: "январь", 2: "февраль", 3: "март", 4: "апрель",
        5: "май", 6: "июнь", 7: "июль", 8: "август",
        9: "сентябрь", 10: "октябрь", 11: "ноябрь", 12: "декабрь",
    }
    month_name = month_names.get(month, str(month))

    lines = [f"Данные за {month_name} {year}:", ""]
    if spend_by_currency:
        spend_str = ", ".join(f"{v} {cur}" for cur, v in spend_by_currency.items())
        lines.append(f"Расходы: {spend_str}")
    if income_by_currency:
        income_str = ", ".join(f"{v} {cur}" for cur, v in income_by_currency.items())
        lines.append(f"Доходы: {income_str}")

    if top_tags:
        lines.append("\nТоп расходы по тегам:")
        prev_map = {t["tag"]: t["amount"] for t in prev_top_tags}
        for t in top_tags[:8]:
            tag = t["tag"]
            amt = t["amount"]
            prev_amt = prev_map.get(tag)
            if prev_amt and prev_amt > 0:
                pct = ((amt - prev_amt) / prev_amt * 100)
                sign = "+" if pct >= 0 else ""
                lines.append(f"  #{tag}: {amt:.0f} ({sign}{pct:.0f}% к прошлому месяцу)")
            else:
                lines.append(f"  #{tag}: {amt:.0f}")

    return "\n".join(lines)


async def get_insights(
    household_id: str,
    year: int,
    month: int,
    db: Session,
) -> str:
    """Call OpenAI and return insights text. Returns error message on failure."""
    from app.application.services.finance_service import FinanceService
    from app.infrastructure.config.settings import get_settings

    try:
        settings = get_settings()
        api_key = settings.openai_api_key
        model = getattr(settings, "openai_model", "gpt-4.1-mini")
    except Exception:
        return "Не удалось получить инсайты. Попробуй позже."

    # Current month summary
    svc = FinanceService(db)
    for_date = date(year, month, 1)
    summary = svc.month_summary(household_id, for_date=for_date)

    # Previous month summary for comparison
    if month == 1:
        prev_date = date(year - 1, 12, 1)
    else:
        prev_date = date(year, month - 1, 1)
    prev_summary = svc.month_summary(household_id, for_date=prev_date)

    user_prompt = _build_user_prompt(
        year=year,
        month=month,
        spend_by_currency=summary["spend_by_currency"],
        income_by_currency=summary["income_by_currency"],
        top_tags=summary["top_tags"],
        prev_top_tags=prev_summary["top_tags"],
    )

    try:
        from openai import AsyncOpenAI
        client = AsyncOpenAI(api_key=api_key)
        response = await client.chat.completions.create(
            model=model,
            max_tokens=600,
            messages=[
                {"role": "system", "content": _SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt},
            ],
        )
        return response.choices[0].message.content or "Пустой ответ от OpenAI."
    except Exception as exc:
        log.warning("insights_service: OpenAI error: %s", exc)
        return "Не удалось получить инсайты. Попробуй позже."
