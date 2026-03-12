from datetime import date
from decimal import Decimal
from typing import Any

from pydantic import BaseModel


class SQLImportRequest(BaseModel):
    household_id: str
    source_name: str
    sql_query: str
    default_currency: str = "USD"
    source_account_id: str | None = None
    source_owner_id: str | None = None
    force_expense_source: bool = True


class MonthSummaryOut(BaseModel):
    period: dict[str, str]
    totals: dict[str, Decimal]
    top_categories: list[dict[str, Any]]
    biggest_expenses: list[dict[str, Any]]
    upcoming_until_month_end: list[dict[str, Any]]


class UpcomingOut(BaseModel):
    items: list[dict[str, Any]]


class TransactionCorrectionUpdate(BaseModel):
    category_id: str | None = None
    recurring_payment_id: str | None = None


class MonthQuery(BaseModel):
    household_id: str
    as_of: date | None = None
