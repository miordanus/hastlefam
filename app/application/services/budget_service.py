"""budget_service.py — Tag budget tracking and alerting.

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
from app.infrastructure.db.models import TagBudget, Transaction

log = logging.getLogger(__name__)

_ALERT_THRESHOLDS = [80, 100]  # percent


def apply_rollover(
    household_id: str,
    month_key: str,
    session: Session,
) -> None:
    """Carry unused budget from previous month to current month for rollover-enabled TagBudgets.

    For each budget with rollover_enabled=True in the previous month:
    - If remainder (limit - actual_spent) > 0: set current month's rollover_amount = remainder
    - If remainder <= 0: rollover_amount = 0 (overspend is not carried)
    """
    hid = _uuid.UUID(household_id) if isinstance(household_id, str) else household_id

    try:
        year, month = int(month_key[:4]), int(month_key[5:7])
    except (ValueError, IndexError):
        return

    # Compute prev month key
    if month == 1:
        prev_year, prev_month = year - 1, 12
    else:
        prev_year, prev_month = year, month - 1
    prev_month_key = f"{prev_year}-{prev_month:02d}"

    import calendar
    prev_month_start = datetime(prev_year, prev_month, 1, tzinfo=timezone.utc)
    prev_last_day = calendar.monthrange(prev_year, prev_month)[1]
    prev_month_end = datetime(prev_year, prev_month, prev_last_day, 23, 59, 59, tzinfo=timezone.utc)

    prev_budgets = (
        session.query(TagBudget)
        .filter(
            TagBudget.household_id == hid,
            TagBudget.month_key == prev_month_key,
            TagBudget.rollover_enabled.is_(True),
        )
        .all()
    )

    for prev_budget in prev_budgets:
        actual_rows = (
            session.query(Transaction)
            .filter(
                Transaction.household_id == hid,
                Transaction.occurred_at >= prev_month_start,
                Transaction.occurred_at <= prev_month_end,
                Transaction.direction == TransactionDirection.EXPENSE,
                Transaction.is_planned == False,  # noqa: E712
                Transaction.is_skipped == False,  # noqa: E712
                Transaction.primary_tag == prev_budget.tag,
            )
            .all()
        )
        actual_spent = sum(Decimal(str(tx.amount)) for tx in actual_rows)
        prev_limit = Decimal(str(prev_budget.limit_amount))
        remainder = prev_limit - actual_spent
        rollover_amount = max(Decimal("0"), remainder)

        # Find or create current month budget for same tag
        curr_budget = (
            session.query(TagBudget)
            .filter(
                TagBudget.household_id == hid,
                TagBudget.month_key == month_key,
                TagBudget.tag == prev_budget.tag,
            )
            .first()
        )
        if curr_budget is None:
            curr_budget = TagBudget(
                household_id=hid,
                month_key=month_key,
                tag=prev_budget.tag,
                limit_amount=prev_budget.limit_amount,
                currency=prev_budget.currency,
                rollover_enabled=True,
                rollover_amount=rollover_amount,
            )
            session.add(curr_budget)
        else:
            curr_budget.rollover_amount = rollover_amount

    if prev_budgets:
        session.commit()


def get_budget_status(
    household_id: str,
    month_key: str,
    session: Session,
) -> list[dict[str, Any]]:
    """Return per-tag budget status for the given month_key (e.g. '2026-03').

    Each entry contains:
      - category_name: str  (= tag, kept for backward compat with month.py)
      - tag: str
      - budget_id: str
      - limit_amount: Decimal
      - rollover_amount: Decimal
      - effective_limit: Decimal  (limit + rollover)
      - currency: str
      - actual_spent: Decimal   (is_planned=False, is_skipped=False)
      - planned_amount: Decimal (is_planned=True AND occurred_at > now())
      - remaining_after_planned: Decimal
      - pct_used: float  (actual / effective_limit * 100)
      - status: 'ok' | 'at_risk' | 'over_budget'
      - rollover_enabled: bool
    """
    hid = _uuid.UUID(household_id) if isinstance(household_id, str) else household_id

    # Apply rollover for current month before computing status
    from datetime import date
    current_month_key = date.today().strftime("%Y-%m")
    if month_key == current_month_key:
        apply_rollover(household_id, month_key, session)

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
        session.query(TagBudget)
        .filter(
            TagBudget.household_id == hid,
            TagBudget.month_key == month_key,
        )
        .all()
    )

    result = []
    for budget in budgets:
        tag = budget.tag

        # actual_spent: is_planned=False, is_skipped=False, direction=EXPENSE, tag matches
        actual_rows = (
            session.query(Transaction)
            .filter(
                Transaction.household_id == hid,
                Transaction.occurred_at >= month_start,
                Transaction.occurred_at <= month_end,
                Transaction.direction == TransactionDirection.EXPENSE,
                Transaction.is_planned == False,  # noqa: E712
                Transaction.is_skipped == False,  # noqa: E712
                Transaction.primary_tag == tag,
            )
            .all()
        )
        actual_spent = sum(Decimal(str(tx.amount)) for tx in actual_rows)

        # planned_amount: is_planned=True, occurred_at > now, tag matches
        planned_rows = (
            session.query(Transaction)
            .filter(
                Transaction.household_id == hid,
                Transaction.occurred_at >= month_start,
                Transaction.occurred_at <= month_end,
                Transaction.occurred_at > now,
                Transaction.direction == TransactionDirection.EXPENSE,
                Transaction.is_planned == True,  # noqa: E712
                Transaction.is_skipped == False,  # noqa: E712
                Transaction.primary_tag == tag,
            )
            .all()
        )
        planned_amount = sum(Decimal(str(tx.amount)) for tx in planned_rows)

        limit = Decimal(str(budget.limit_amount))
        rollover = Decimal(str(budget.rollover_amount)) if budget.rollover_amount else Decimal("0")
        effective_limit = limit + rollover
        remaining = effective_limit - actual_spent - planned_amount
        pct_used = float(actual_spent / effective_limit * 100) if effective_limit > 0 else 0.0

        if pct_used >= 100:
            status = "over_budget"
        elif pct_used >= 80:
            status = "at_risk"
        else:
            status = "ok"

        result.append({
            "budget_id": str(budget.id),
            "category_name": tag,  # backward compat with month.py display
            "tag": tag,
            "limit_amount": limit,
            "rollover_amount": rollover,
            "effective_limit": effective_limit,
            "rollover_enabled": bool(budget.rollover_enabled),
            "currency": budget.currency,
            "actual_spent": actual_spent,
            "planned_amount": planned_amount,
            "remaining_after_planned": remaining,
            "pct_used": pct_used,
            "status": status,
        })

    return result


def get_budget_status_via_rest(household_id: str, month_key: str) -> list[dict[str, Any]]:
    """REST-API mirror of get_budget_status(). Talks to PostgREST via
    SupabaseClient instead of opening a Postgres socket (the web host is
    REST-only). Same return shape and ЗАКОН filters.

    Uses the *stored* rollover_amount (does NOT run apply_rollover, which writes).
    """
    import calendar

    from app.infrastructure.config.settings import get_settings
    from app.infrastructure.supabase import SupabaseClient

    try:
        year, month = int(month_key[:4]), int(month_key[5:7])
    except (ValueError, IndexError):
        return []

    month_start = datetime(year, month, 1, tzinfo=timezone.utc)
    last_day = calendar.monthrange(year, month)[1]
    month_end = datetime(year, month, last_day, 23, 59, 59, tzinfo=timezone.utc)
    now = datetime.now(timezone.utc)

    settings = get_settings()
    with SupabaseClient(settings.supabase_url, settings.supabase_service_role_key) as sb:
        budgets = sb.get("tag_budgets", {
            "select": "id,tag,limit_amount,rollover_amount,rollover_enabled,currency",
            "household_id": f"eq.{household_id}",
            "month_key": f"eq.{month_key}",
        })
        txs = sb.get("transactions", {
            "select": "primary_tag,amount,direction,is_planned,is_skipped,occurred_at",
            "household_id": f"eq.{household_id}",
            "direction": "eq.expense",
            "is_skipped": "eq.false",
            "occurred_at": f"gte.{month_start.isoformat()}",
        })

    def _parse(iso: str | None) -> datetime | None:
        if not iso:
            return None
        try:
            dt = datetime.fromisoformat(str(iso).replace("Z", "+00:00"))
        except ValueError:
            return None
        return dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt

    # Keep only this month's expense rows (the stub doesn't apply the date filter).
    month_rows = []
    for t in txs:
        if (t.get("direction") or "").lower() != "expense" or t.get("is_skipped"):
            continue
        occ = _parse(t.get("occurred_at"))
        if occ is None or not (month_start <= occ <= month_end):
            continue
        month_rows.append((t, occ))

    result = []
    for budget in budgets:
        tag = budget.get("tag")
        actual_spent = Decimal("0")
        planned_amount = Decimal("0")
        for t, occ in month_rows:
            if t.get("primary_tag") != tag:
                continue
            amt = Decimal(str(t.get("amount") or 0))
            if t.get("is_planned"):
                if occ > now:
                    planned_amount += amt
            else:
                actual_spent += amt

        limit = Decimal(str(budget.get("limit_amount") or 0))
        rollover = Decimal(str(budget.get("rollover_amount") or 0))
        effective_limit = limit + rollover
        remaining = effective_limit - actual_spent - planned_amount
        pct_used = float(actual_spent / effective_limit * 100) if effective_limit > 0 else 0.0
        if pct_used >= 100:
            status = "over_budget"
        elif pct_used >= 80:
            status = "at_risk"
        else:
            status = "ok"

        result.append({
            "budget_id": str(budget.get("id")),
            "category_name": tag,
            "tag": tag,
            "limit_amount": limit,
            "rollover_amount": rollover,
            "effective_limit": effective_limit,
            "rollover_enabled": bool(budget.get("rollover_enabled")),
            "currency": budget.get("currency") or "RUB",
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
        name = s["tag"]
        limit = s["effective_limit"]
        actual = s["actual_spent"]
        cur = s["currency"]

        try:
            if s["status"] == "over_budget":
                overage = actual - limit
                await bot.send_message(
                    chat_id,
                    f"🔴 Перерасход по тегу «{name}»: "
                    f"{_fmt(actual)} {cur} / лимит {_fmt(limit)} {cur} "
                    f"(+{_fmt(overage)} {cur})",
                )
            elif s["status"] == "at_risk":
                remaining = limit - actual
                await bot.send_message(
                    chat_id,
                    f"⚠️ Тег «{name}» на {pct:.0f}% от лимита. "
                    f"Осталось {_fmt(remaining)} {cur}.",
                )
        except Exception as exc:
            log.warning("check_and_alert: failed to send alert: %s", exc)


def _fmt(amount: Decimal) -> str:
    """Format amount with space thousands separator. No trailing zeros for whole numbers."""
    if amount == int(amount):
        return f"{int(amount):,}".replace(",", " ")
    return f"{amount:,.2f}".replace(",", " ")
