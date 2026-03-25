"""budget_service.py — Category budget tracking and alerting.

ЗАКОН: actual_spent фильтрует is_planned=False.
       planned_amount фильтрует is_planned=True AND occurred_at > now().
       Смешивать нельзя нигде.
"""
from __future__ import annotations

import logging
import uuid as _uuid
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

from sqlalchemy.orm import Session

from app.domain.enums import TransactionDirection
from app.infrastructure.db.models import CategoryBudget, FinanceCategory, Transaction

log = logging.getLogger(__name__)

_ALERT_THRESHOLDS = [80, 100]  # percent


def get_budget_status(
    household_id: str,
    month_key: str,
    session: Session,
) -> list[dict[str, Any]]:
    """Return per-category budget status for the given month_key (e.g. '2026-03').

    Each entry contains:
      - category_name: str
      - limit_amount: Decimal
      - currency: str
      - actual_spent: Decimal   (is_planned=False)
      - planned_amount: Decimal (is_planned=True AND occurred_at > now())
      - remaining_after_planned: Decimal
      - pct_used: float  (actual / limit * 100)
      - status: 'ok' | 'at_risk' | 'over_budget'
    """
    hid = _uuid.UUID(household_id) if isinstance(household_id, str) else household_id

    # Parse month_key into date range
    try:
        year, month = int(month_key[:4]), int(month_key[5:7])
    except (ValueError, IndexError):
        return []

    import calendar
    month_start = datetime(year, month, 1, tzinfo=timezone.utc)
    last_day = calendar.monthrange(year, month)[1]
    month_end = datetime(year, month, last_day, 23, 59, 59, tzinfo=timezone.utc)
    now = datetime.now(timezone.utc)

    budgets = (
        session.query(CategoryBudget)
        .filter(
            CategoryBudget.household_id == hid,
            CategoryBudget.month_key == month_key,
        )
        .all()
    )

    result = []
    for budget in budgets:
        # Resolve category name
        category_name: str = month_key  # fallback
        if budget.category_id:
            cat = session.get(FinanceCategory, budget.category_id)
            if cat:
                category_name = cat.name
        else:
            category_name = "Без категории"

        # actual_spent: is_planned=False, direction=EXPENSE, tag matches category name
        actual_rows = (
            session.query(Transaction)
            .filter(
                Transaction.household_id == hid,
                Transaction.occurred_at >= month_start,
                Transaction.occurred_at <= month_end,
                Transaction.direction == TransactionDirection.EXPENSE,
                Transaction.is_planned == False,  # noqa: E712
                Transaction.primary_tag == category_name.lower(),
            )
            .all()
        )
        actual_spent = sum(Decimal(str(tx.amount)) for tx in actual_rows)

        # planned_amount: is_planned=True, occurred_at > now
        planned_rows = (
            session.query(Transaction)
            .filter(
                Transaction.household_id == hid,
                Transaction.occurred_at >= month_start,
                Transaction.occurred_at <= month_end,
                Transaction.occurred_at > now,
                Transaction.direction == TransactionDirection.EXPENSE,
                Transaction.is_planned == True,  # noqa: E712
                Transaction.primary_tag == category_name.lower(),
            )
            .all()
        )
        planned_amount = sum(Decimal(str(tx.amount)) for tx in planned_rows)

        limit = Decimal(str(budget.limit_amount))
        remaining = limit - actual_spent - planned_amount
        pct_used = float(actual_spent / limit * 100) if limit > 0 else 0.0

        if pct_used >= 100:
            status = "over_budget"
        elif pct_used >= 80:
            status = "at_risk"
        else:
            status = "ok"

        result.append({
            "budget_id": str(budget.id),
            "category_name": category_name,
            "limit_amount": limit,
            "currency": budget.currency,
            "actual_spent": actual_spent,
            "planned_amount": planned_amount,
            "remaining_after_planned": remaining,
            "pct_used": pct_used,
            "status": status,
        })

    return result


async def check_and_alert(
    household_id: str,
    session: Session,
    bot,
    chat_id: int,
) -> None:
    """Check budget thresholds after a capture and send a push if a threshold was crossed.

    Alerts at 80% (at_risk) and 100% (over_budget) — one message per crossing.
    """
    from datetime import date
    month_key = date.today().strftime("%Y-%m")
    statuses = get_budget_status(household_id, month_key, session)

    for s in statuses:
        pct = s["pct_used"]
        name = s["category_name"]
        limit = s["limit_amount"]
        actual = s["actual_spent"]
        cur = s["currency"]

        try:
            if s["status"] == "over_budget":
                overage = actual - limit
                await bot.send_message(
                    chat_id,
                    f"🔴 Перерасход в категории «{name}»: "
                    f"{_fmt(actual)} {cur} / лимит {_fmt(limit)} {cur} "
                    f"(+{_fmt(overage)} {cur})",
                )
            elif s["status"] == "at_risk":
                remaining = limit - actual
                await bot.send_message(
                    chat_id,
                    f"⚠️ Категория «{name}» на {pct:.0f}% от лимита. "
                    f"Осталось {_fmt(remaining)} {cur}.",
                )
        except Exception as exc:
            log.warning("check_and_alert: failed to send alert: %s", exc)


def _fmt(amount: Decimal) -> str:
    """Format amount with space thousands separator."""
    parts = f"{amount:,.2f}".replace(",", " ")
    return parts
