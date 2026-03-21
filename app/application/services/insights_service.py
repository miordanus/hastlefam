"""insights_service.py — OpenAI-powered monthly finance insights.

Collects monthly data, builds a structured prompt with spend breakdown,
MoM comparisons, anomaly hints, and top merchants. Calls gpt-4.1-mini.
Degrades gracefully: returns error string if OpenAI is unavailable.
"""
from __future__ import annotations

import logging
from datetime import date
from decimal import Decimal

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.domain.enums import TransactionDirection

log = logging.getLogger(__name__)

_SYSTEM_PROMPT = (
    "Ты финансовый советник семейного бюджета из двух человек. "
    "Отвечай на русском, структурировано.\n\n"
    "Формат ответа:\n"
    "📊 ВЫВОДЫ (3-5 пунктов):\n"
    "- Конкретные наблюдения с цифрами\n"
    "- Сравнение с прошлым месяцем (рост/падение %)\n"
    "- Аномалии и выбросы\n\n"
    "💡 РЕКОМЕНДАЦИИ (1-3 пункта):\n"
    "- Конкретные действия, а не общие советы\n"
    "- Привязаны к данным\n\n"
    "Не пиши банальности вроде 'ведите бюджет'. Будь конкретен."
)


def _format_amount(v: Decimal) -> str:
    return f"{v:,.0f}".replace(",", " ")


def _build_user_prompt(
    year: int,
    month: int,
    spend_by_currency: dict,
    income_by_currency: dict,
    top_tags: list,
    prev_spend_by_currency: dict,
    prev_income_by_currency: dict,
    prev_top_tags: list,
    top_merchants: list[tuple[str, Decimal, int]],
    untagged_count: int,
    total_tx_count: int,
) -> str:
    month_names = {
        1: "январь", 2: "февраль", 3: "март", 4: "апрель",
        5: "май", 6: "июнь", 7: "июль", 8: "август",
        9: "сентябрь", 10: "октябрь", 11: "ноябрь", 12: "декабрь",
    }
    month_name = month_names.get(month, str(month))

    lines = [f"## Данные за {month_name} {year}", ""]

    # ─── Spend breakdown ────────────────────────────────────────────
    lines.append("### Расходы по валютам:")
    if spend_by_currency:
        for cur, v in spend_by_currency.items():
            prev_v = prev_spend_by_currency.get(cur)
            if prev_v and prev_v > 0:
                pct = (v - prev_v) / prev_v * 100
                sign = "+" if pct >= 0 else ""
                lines.append(f"  {cur}: {_format_amount(v)} ({sign}{pct:.0f}% к прошлому мес.)")
            else:
                lines.append(f"  {cur}: {_format_amount(v)}")
    else:
        lines.append("  Расходов нет")

    # ─── Income breakdown ───────────────────────────────────────────
    lines.append("\n### Доходы по валютам:")
    if income_by_currency:
        for cur, v in income_by_currency.items():
            prev_v = prev_income_by_currency.get(cur)
            if prev_v and prev_v > 0:
                pct = (v - prev_v) / prev_v * 100
                sign = "+" if pct >= 0 else ""
                lines.append(f"  {cur}: {_format_amount(v)} ({sign}{pct:.0f}% к прошлому мес.)")
            else:
                lines.append(f"  {cur}: {_format_amount(v)}")
    else:
        lines.append("  Доходов нет")

    # ─── Top tags with MoM ──────────────────────────────────────────
    if top_tags:
        prev_map = {t["tag"]: t["amount"] for t in prev_top_tags}
        lines.append("\n### Расходы по категориям (теги):")
        for t in top_tags[:8]:
            tag = t["tag"]
            amt = t["amount"]
            prev_amt = prev_map.get(tag)
            if prev_amt and prev_amt > 0:
                pct = (amt - prev_amt) / prev_amt * 100
                sign = "+" if pct >= 0 else ""
                lines.append(f"  #{tag}: {_format_amount(amt)} ({sign}{pct:.0f}%)")
            else:
                lines.append(f"  #{tag}: {_format_amount(amt)} (новая категория)")

    # ─── Top merchants ──────────────────────────────────────────────
    if top_merchants:
        lines.append("\n### Топ мерчантов по сумме:")
        for merchant, amount, count in top_merchants[:7]:
            lines.append(f"  {merchant}: {_format_amount(amount)} ({count} транз.)")

    # ─── Stats ──────────────────────────────────────────────────────
    lines.append(f"\n### Статистика:")
    lines.append(f"  Всего транзакций: {total_tx_count}")
    if untagged_count:
        lines.append(f"  Без тега: {untagged_count} ({untagged_count/max(total_tx_count,1)*100:.0f}%)")

    return "\n".join(lines)


def _get_top_merchants(db: Session, household_id, year: int, month: int) -> list[tuple[str, Decimal, int]]:
    """Return top merchants by total spend for the given month."""
    from app.infrastructure.db.models import Transaction
    import calendar
    from datetime import datetime, timezone

    month_start = datetime(year, month, 1, tzinfo=timezone.utc)
    last_day = calendar.monthrange(year, month)[1]
    month_end = datetime(year, month, last_day, 23, 59, 59, tzinfo=timezone.utc)

    rows = (
        db.query(
            Transaction.merchant_raw,
            func.sum(Transaction.amount).label("total"),
            func.count(Transaction.id).label("cnt"),
        )
        .filter(
            Transaction.household_id == household_id,
            Transaction.occurred_at >= month_start,
            Transaction.occurred_at <= month_end,
            Transaction.direction == TransactionDirection.EXPENSE,
            Transaction.merchant_raw.isnot(None),
        )
        .group_by(Transaction.merchant_raw)
        .order_by(func.sum(Transaction.amount).desc())
        .limit(10)
        .all()
    )
    return [(r.merchant_raw, Decimal(str(r.total)), r.cnt) for r in rows]


async def get_insights(
    household_id: str,
    year: int,
    month: int,
    db: Session,
) -> str:
    """Call OpenAI and return insights text. Returns error message on failure."""
    import uuid as _uuid
    from app.application.services.finance_service import FinanceService
    from app.infrastructure.config.settings import get_settings

    try:
        settings = get_settings()
        api_key = settings.openai_api_key
        model = getattr(settings, "openai_model", "gpt-4.1-mini")
    except Exception:
        return "Не удалось получить инсайты. Попробуй позже."

    svc = FinanceService(db)
    hid = _uuid.UUID(household_id) if isinstance(household_id, str) else household_id

    # Current month — use last day so we get full month data
    for_date = date(year, month, 1)
    summary = svc.month_summary(household_id, for_date=for_date)

    # Previous month
    if month == 1:
        prev_date = date(year - 1, 12, 1)
    else:
        prev_date = date(year, month - 1, 1)
    prev_summary = svc.month_summary(household_id, for_date=prev_date)

    # Top merchants (SQL aggregation)
    top_merchants = _get_top_merchants(db, hid, year, month)

    total_tx_count = summary.get("expense_count", 0) + summary.get("income_count", 0)

    user_prompt = _build_user_prompt(
        year=year,
        month=month,
        spend_by_currency=summary["spend_by_currency"],
        income_by_currency=summary["income_by_currency"],
        top_tags=summary["top_tags"],
        prev_spend_by_currency=prev_summary["spend_by_currency"],
        prev_income_by_currency=prev_summary["income_by_currency"],
        prev_top_tags=prev_summary["top_tags"],
        top_merchants=top_merchants,
        untagged_count=summary.get("untagged_count", 0),
        total_tx_count=total_tx_count,
    )

    try:
        from openai import AsyncOpenAI
        client = AsyncOpenAI(api_key=api_key)
        response = await client.chat.completions.create(
            model=model,
            max_tokens=800,
            temperature=0.3,
            messages=[
                {"role": "system", "content": _SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt},
            ],
        )
        return response.choices[0].message.content or "Пустой ответ от OpenAI."
    except Exception as exc:
        log.warning("insights_service: OpenAI error: %s", exc)
        return "Не удалось получить инсайты. Попробуй позже."
