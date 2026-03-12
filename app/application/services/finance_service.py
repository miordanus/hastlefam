from __future__ import annotations

import calendar
import uuid as _uuid
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from typing import Any

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.domain.enums import TransactionDirection
from app.infrastructure.db.models import FinanceCategory, RecurringPayment, Transaction


class FinanceService:
    def __init__(self, db: Session):
        self.db = db

    def month_summary(self, household_id: str, for_date: date | None = None) -> dict[str, Any]:
        today = for_date or datetime.now(timezone.utc).date()
        month_start = today.replace(day=1)
        month_end = today.replace(day=calendar.monthrange(today.year, today.month)[1])
        hid = _uuid.UUID(household_id) if isinstance(household_id, str) else household_id

        month_start_dt = datetime(month_start.year, month_start.month, month_start.day, tzinfo=timezone.utc)
        today_end_dt = datetime(today.year, today.month, today.day, 23, 59, 59, tzinfo=timezone.utc)

        rows = (
            self.db.query(Transaction)
            .filter(
                Transaction.household_id == hid,
                Transaction.occurred_at >= month_start_dt,
                Transaction.occurred_at <= today_end_dt,
            )
            .all()
        )

        total_spend = Decimal("0")
        total_income = Decimal("0")
        biggest_expenses: list[dict[str, Any]] = []
        by_category: dict[str, Decimal] = {}

        category_ids = {tx.category_id for tx in rows if tx.category_id}
        categories_map: dict[str, str] = {}
        if category_ids:
            cats = self.db.query(FinanceCategory).filter(FinanceCategory.id.in_(category_ids)).all()
            categories_map = {str(c.id): c.name for c in cats}

        for tx in rows:
            amount = Decimal(str(tx.amount))
            if tx.direction == TransactionDirection.EXPENSE:
                total_spend += amount
                biggest_expenses.append(
                    {
                        "amount": amount,
                        "merchant": tx.merchant_raw or tx.description_raw or tx.description or "unknown",
                        "occurred_at": tx.occurred_at.date().isoformat(),
                    }
                )
                category_name = categories_map.get(str(tx.category_id), "Uncategorized") if tx.category_id else "Uncategorized"
                by_category[category_name] = by_category.get(category_name, Decimal("0")) + amount
            elif tx.direction == TransactionDirection.INCOME:
                total_income += amount

        top_categories = sorted(by_category.items(), key=lambda kv: kv[1], reverse=True)[:5]
        biggest_expenses = sorted(biggest_expenses, key=lambda x: x["amount"], reverse=True)[:5]

        upcoming_until_month_end = self.upcoming_payments(household_id, until_date=month_end)

        return {
            "period": {"month_start": month_start.isoformat(), "today": today.isoformat()},
            "totals": {"spend_mtd": total_spend, "income_mtd": total_income},
            "top_categories": [{"category": k, "amount": v} for k, v in top_categories],
            "biggest_expenses": biggest_expenses,
            "upcoming_until_month_end": upcoming_until_month_end,
        }

    def upcoming_payments(self, household_id: str, days: int = 7, until_date: date | None = None) -> list[dict[str, Any]]:
        today = datetime.now(timezone.utc).date()
        last_day = until_date or (today + timedelta(days=days))
        hid = _uuid.UUID(household_id) if isinstance(household_id, str) else household_id

        rec_rows = (
            self.db.query(RecurringPayment)
            .filter(
                RecurringPayment.household_id == hid,
                RecurringPayment.is_active.is_(True),
                RecurringPayment.next_due_date >= today,
                RecurringPayment.next_due_date <= last_day,
            )
            .order_by(RecurringPayment.next_due_date.asc())
            .all()
        )

        result: list[dict[str, Any]] = []
        for rec in rec_rows:
            result.append(
                {
                    "id": str(rec.id),
                    "title": rec.title,
                    "amount": rec.amount_expected,
                    "currency": rec.currency.value,
                    "due_date": rec.next_due_date.isoformat(),
                    "owner_id": str(rec.owner_id) if rec.owner_id else None,
                    "category_id": str(rec.category_id) if rec.category_id else None,
                    "account_id": str(rec.account_id) if rec.account_id else None,
                }
            )
        return result
