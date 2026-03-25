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

_SYSTEM_PROMPT = """\
Ты финансовый советник домашнего бюджета. Правила без исключений:
- Отвечай на русском, строго 3-5 коротких буллетов
- Факт (monthly_actual, is_planned=false) и план (monthly_planned, is_planned=true) — всегда разделяй, никогда не смешивай
- Максимум 1 предупреждение (warning), максимум 1 рекомендация
- Если месяц почти пустой (< 5 транзакций) — не генерируй 5 инсайтов, скажи что данных мало
- Не придумывай объяснения — только то что видишь в данных
- Не пиши "терапию" и мотивацию — только факты и выводы
"""


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
            Transaction.is_planned == False,  # noqa: E712 — ЗАКОН: actual only
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
    import json
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

    for_date = date(year, month, 1)
    summary = svc.month_summary(household_id, for_date=for_date)

    if month == 1:
        prev_date = date(year - 1, 12, 1)
    else:
        prev_date = date(year, month - 1, 1)
    prev_summary = svc.month_summary(household_id, for_date=prev_date)

    # Planned totals (is_planned=True)
    planned_totals = svc.get_planned_total(household_id, year, month)

    top_merchants = _get_top_merchants(db, hid, year, month)
    total_tx_count = summary.get("expense_count", 0) + summary.get("income_count", 0)

    # Budget statuses
    budget_statuses = []
    try:
        from app.application.services.budget_service import get_budget_status
        month_key = f"{year}-{month:02d}"
        budget_statuses = get_budget_status(household_id, month_key, db)
    except Exception:
        pass

    # Category deltas (MoM)
    prev_map = {t["tag"]: t["amount"] for t in prev_summary.get("top_tags", [])}
    category_deltas = []
    for t in summary.get("top_tags", []):
        tag = t["tag"]
        amt = t["amount"]
        prev_amt = prev_map.get(tag)
        if prev_amt and prev_amt > 0:
            pct = float((amt - prev_amt) / prev_amt * 100)
        else:
            pct = None
        category_deltas.append({"tag": tag, "amount": float(amt), "prev_amount": float(prev_amt) if prev_amt else None, "mom_pct": pct})

    # Build structured JSON context
    context = {
        "month": f"{year}-{month:02d}",
        "monthly_actual": {
            "spend_by_currency": {k: float(v) for k, v in summary["spend_by_currency"].items()},
            "income_by_currency": {k: float(v) for k, v in summary["income_by_currency"].items()},
            "total_tx_count": total_tx_count,
        },
        "monthly_planned": {
            "spend_by_currency": {k: float(v) for k, v in planned_totals.items()},
        },
        "budget_statuses": [
            {
                "category": s["category_name"],
                "limit": float(s["limit_amount"]),
                "actual_spent": float(s["actual_spent"]),
                "planned_amount": float(s["planned_amount"]),
                "pct_used": s["pct_used"],
                "status": s["status"],
            }
            for s in budget_statuses
        ],
        "category_deltas": category_deltas,
        "top_merchants": [
            {"name": m, "amount": float(a), "count": c}
            for m, a, c in top_merchants[:7]
        ],
        "untagged_count": summary.get("untagged_count", 0),
    }

    user_prompt = (
        f"Данные за {year}-{month:02d}:\n"
        f"```json\n{json.dumps(context, ensure_ascii=False, indent=2)}\n```\n\n"
        "Дай 3-5 буллетов инсайтов."
    )

    try:
        from openai import AsyncOpenAI
        client = AsyncOpenAI(api_key=api_key)
        response = await client.chat.completions.create(
            model=model,
            max_tokens=600,
            temperature=0.2,
            messages=[
                {"role": "system", "content": _SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt},
            ],
        )
        return response.choices[0].message.content or "Пустой ответ от OpenAI."
    except Exception as exc:
        log.warning("insights_service: OpenAI error: %s", exc)
        return "Не удалось получить инсайты. Попробуй позже."
