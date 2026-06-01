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


class TransactionCreate(BaseModel):
    household_id: str
    amount: Decimal
    currency: str = "RUB"
    direction: str = "expense"          # income | expense | exchange | transfer
    occurred_at: date
    primary_tag: str | None = None
    account_id: str | None = None
    merchant: str | None = None
    user_id: str | None = None
    is_planned: bool = False


class TransactionUpdate(BaseModel):
    amount: Decimal | None = None
    currency: str | None = None
    direction: str | None = None
    occurred_at: date | None = None
    primary_tag: str | None = None
    account_id: str | None = None
    merchant: str | None = None


class BudgetUpsert(BaseModel):
    household_id: str
    month_key: str                      # 'YYYY-MM'
    tag: str
    limit_amount: Decimal
    currency: str = "RUB"
    rollover_enabled: bool | None = None
