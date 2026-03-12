from __future__ import annotations

import calendar
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

        rows = (
            self.db.query(Transaction)
            .filter(
                Transaction.household_id == household_id,
                func.date(Transaction.occurred_at) >= month_start,
                func.date(Transaction.occurred_at) <= today,
            )
            .all()
        )

        total_spend = Decimal("0")
        total_income = Decimal("0")
        biggest_expenses: list[dict[str, Any]] = []
        by_category: dict[str, Decimal] = {}

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
                category_name = "Uncategorized"
                if tx.category_id:
                    category = self.db.get(FinanceCategory, tx.category_id)
                    if category:
                        category_name = category.name
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

        rec_rows = (
            self.db.query(RecurringPayment)
            .filter(
                RecurringPayment.household_id == household_id,
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
