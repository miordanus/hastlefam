from datetime import date
from decimal import Decimal
from typing import Any

from pydantic import BaseModel, field_validator

from app.domain.enums import Currency, TransactionDirection


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

    @field_validator("amount")
    @classmethod
    def amount_positive(cls, v: Decimal) -> Decimal:
        if v <= 0:
            raise ValueError("amount must be greater than 0")
        return v

    @field_validator("direction")
    @classmethod
    def direction_valid(cls, v: str) -> str:
        valid = [e.value for e in TransactionDirection]
        if v not in valid:
            raise ValueError(f"direction must be one of {valid}")
        return v

    @field_validator("currency")
    @classmethod
    def currency_valid(cls, v: str) -> str:
        valid = [e.value for e in Currency]
        match = next((x for x in valid if x.upper() == v.upper()), None)
        if match is None:
            raise ValueError(f"currency must be one of {valid}")
        return match

    @field_validator("merchant")
    @classmethod
    def merchant_strip(cls, v: str | None) -> str | None:
        if v is None:
            return None
        stripped = v.strip()
        return stripped if stripped else None


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


class BalanceSnapshotCreate(BaseModel):
    household_id: str
    account_id: str
    actual_balance: Decimal
    note: str | None = None


class TagAssignment(BaseModel):
    tx_id: str
    tag: str | None = None


class BulkTagRequest(BaseModel):
    household_id: str
    assignments: list[TagAssignment]


class AccountCreate(BaseModel):
    household_id: str
    name: str
    currency: str = "RUB"
    owner_user_id: str | None = None
    is_shared: bool = True
