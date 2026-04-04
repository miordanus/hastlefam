import uuid
from datetime import date, datetime, timezone
from decimal import Decimal

from sqlalchemy import JSON, Boolean, Date, DateTime, Enum, ForeignKey, Index, Numeric, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.domain.enums import (
    CategoryKind,
    Currency,
    DraftType,
    MeetingType,
    NoteType,
    TaskStatus,
    TaskType,
    TransactionDirection,
)
from app.infrastructure.db.base import Base


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _enum_values(enum_cls):
    """Return enum values (not names) so SQLAlchemy sends lowercase to PG."""
    return [e.value for e in enum_cls]


class Household(Base):
    __tablename__ = "households"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc, onupdate=now_utc)


class User(Base):
    __tablename__ = "users"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    household_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("households.id"), nullable=False)
    telegram_id: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc, onupdate=now_utc)


class Owner(Base):
    __tablename__ = "owners"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    household_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("households.id"), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    slug: Mapped[str] = mapped_column(String(32), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc, onupdate=now_utc)


class Area(Base):
    __tablename__ = "areas"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    household_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("households.id"), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    is_default: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc, onupdate=now_utc)


class Sprint(Base):
    __tablename__ = "sprints"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    household_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("households.id"), nullable=False)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    start_date: Mapped[date] = mapped_column(Date, nullable=False)
    end_date: Mapped[date] = mapped_column(Date, nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="planned")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc, onupdate=now_utc)


class Task(Base):
    __tablename__ = "tasks"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    household_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("households.id"), nullable=False, index=True)
    area_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("areas.id"))
    sprint_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("sprints.id"))
    owner_user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    task_type: Mapped[TaskType] = mapped_column(Enum(TaskType, name="task_type_enum", values_callable=_enum_values), default=TaskType.TASK)
    status: Mapped[TaskStatus] = mapped_column(Enum(TaskStatus, name="task_status_enum", values_callable=_enum_values), default=TaskStatus.BACKLOG)
    priority: Mapped[str] = mapped_column(String(16), default="medium")
    due_date: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc, onupdate=now_utc)


class Decision(Base):
    __tablename__ = "decisions"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    household_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("households.id"), nullable=False)
    meeting_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("meetings.id"))
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    decided_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)


class Note(Base):
    __tablename__ = "notes"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    household_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("households.id"), nullable=False)
    author_user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), nullable=False)
    area_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("areas.id"))
    meeting_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("meetings.id"))
    note_type: Mapped[NoteType] = mapped_column(Enum(NoteType, name="note_type_enum", values_callable=_enum_values), default=NoteType.NOTE)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)


class Meeting(Base):
    __tablename__ = "meetings"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    household_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("households.id"), nullable=False)
    meeting_type: Mapped[MeetingType] = mapped_column(Enum(MeetingType, name="meeting_type_enum", values_callable=_enum_values), nullable=False)
    scheduled_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(32), default="scheduled")
    agenda_text: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)


class FinanceCategory(Base):
    __tablename__ = "finance_categories"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    household_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("households.id"))
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    kind: Mapped[CategoryKind] = mapped_column(Enum(CategoryKind, name="category_kind_enum", values_callable=_enum_values), nullable=False)
    is_default: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)


class Account(Base):
    __tablename__ = "accounts"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    household_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("households.id"), nullable=False)
    owner_user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    owner_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("owners.id"))
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    currency: Mapped[Currency] = mapped_column(Enum(Currency, name="currency_enum", values_callable=_enum_values), nullable=False)
    is_shared: Mapped[bool] = mapped_column(Boolean, default=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)


class RawImportTransaction(Base):
    __tablename__ = "raw_import_transactions"
    __table_args__ = (
        Index("ix_raw_import_status_imported_at", "normalization_status", "imported_at"),
    )
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    household_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("households.id"), nullable=False, index=True)
    import_batch_id: Mapped[str] = mapped_column(String(128), nullable=False)
    source_name: Mapped[str] = mapped_column(String(64), nullable=False)
    imported_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)
    raw_payload: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    raw_occurred_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    raw_amount: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    raw_currency: Mapped[str | None] = mapped_column(String(8))
    raw_merchant: Mapped[str | None] = mapped_column(String(255))
    raw_description: Mapped[str | None] = mapped_column(Text)
    normalization_status: Mapped[str] = mapped_column(String(32), default="pending")
    normalization_error: Mapped[str | None] = mapped_column(Text)


class Transaction(Base):
    __tablename__ = "transactions"
    __table_args__ = (
        Index("ix_transactions_household_occurred_at", "household_id", "occurred_at"),
        Index("ix_transactions_account_id", "account_id"),
    )
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    household_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("households.id"), nullable=False)
    owner_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("owners.id"), index=True)
    account_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("accounts.id"))
    category_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("finance_categories.id"))
    user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    direction: Mapped[TransactionDirection] = mapped_column(Enum(TransactionDirection, name="transaction_direction_enum", values_callable=_enum_values), nullable=False)
    amount: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    currency: Mapped[Currency] = mapped_column(Enum(Currency, name="currency_enum", values_callable=_enum_values), nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    merchant_raw: Mapped[str | None] = mapped_column(String(255))
    description_raw: Mapped[str | None] = mapped_column(Text)
    description: Mapped[str | None] = mapped_column(Text)
    source: Mapped[str] = mapped_column(String(64), default="manual")
    raw_import_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("raw_import_transactions.id"))
    parse_status: Mapped[str | None] = mapped_column(String(32))
    parse_confidence: Mapped[Decimal | None] = mapped_column(Numeric(4, 3))
    dedup_fingerprint: Mapped[str | None] = mapped_column(String(128), index=True)
    primary_tag: Mapped[str | None] = mapped_column(String(64), index=True)
    extra_tags: Mapped[list | None] = mapped_column(JSON, default=list)
    # ЗАКОН: is_planned=True НИКОГДА не входит в расходы/доходы.
    # Нарушать нельзя нигде: finance_service, month, ask, insights.
    is_planned: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    # is_skipped=True: planned transaction dismissed by user, hidden from /upcoming
    is_skipped: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    # is_internal_transfer=True: intra-household fund movement (e.g. ATM top-up to credit card).
    # ЗАКОН: НИКОГДА не входит в доходы/расходы. Фильтровать везде: finance_service, month, ask, insights.
    is_internal_transfer: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    # Exchange-specific fields (direction=EXCHANGE only)
    from_amount: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    from_currency: Mapped[str | None] = mapped_column(String(10))
    to_amount: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    to_currency: Mapped[str | None] = mapped_column(String(10))
    exchange_rate: Mapped[Decimal | None] = mapped_column(Numeric(18, 6))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc, onupdate=now_utc)


class RecurringPayment(Base):
    __tablename__ = "recurring_payments"
    __table_args__ = (Index("ix_recurring_due_active", "next_due_date", "is_active"),)
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    household_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("households.id"), nullable=False)
    owner_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("owners.id"), index=True)
    account_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("accounts.id"))
    category_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("finance_categories.id"))
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    amount_expected: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    currency: Mapped[Currency] = mapped_column(Enum(Currency, name="currency_enum", values_callable=_enum_values), nullable=False)
    cadence: Mapped[str] = mapped_column(String(16), nullable=False, default="monthly")
    day_of_month: Mapped[int | None] = mapped_column()
    next_due_date: Mapped[date] = mapped_column(Date, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)


class SavingsGoal(Base):
    __tablename__ = "savings_goals"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    household_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("households.id"), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    target_amount: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    currency: Mapped[Currency] = mapped_column(Enum(Currency, name="currency_enum", values_callable=_enum_values), nullable=False)
    deadline: Mapped[date | None] = mapped_column(Date)
    current_amount: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=0)
    status: Mapped[str] = mapped_column(String(32), default="active")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)


class Reminder(Base):
    __tablename__ = "reminders"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    household_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("households.id"), nullable=False)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), nullable=False)
    entity_type: Mapped[str] = mapped_column(String(64), nullable=False)
    entity_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    remind_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="pending")
    channel: Mapped[str] = mapped_column(String(32), default="telegram")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)


class Digest(Base):
    __tablename__ = "digests"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    household_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("households.id"), nullable=False)
    digest_type: Mapped[str] = mapped_column(String(32), nullable=False)
    period_start: Mapped[date] = mapped_column(Date, nullable=False)
    period_end: Mapped[date] = mapped_column(Date, nullable=False)
    content_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    status: Mapped[str] = mapped_column(String(32), default="draft")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)


class LLMDraft(Base):
    __tablename__ = "llm_drafts"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    household_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("households.id"), nullable=False)
    draft_type: Mapped[DraftType] = mapped_column(Enum(DraftType, name="draft_type_enum", values_callable=_enum_values), nullable=False)
    source_text: Mapped[str] = mapped_column(Text, nullable=False)
    input_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    output_json: Mapped[dict | None] = mapped_column(JSON)
    validation_status: Mapped[str] = mapped_column(String(32), default="pending")
    error_text: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)


class PlannedPayment(Base):
    __tablename__ = "planned_payments"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    household_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("households.id"), nullable=False, index=True)
    owner_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("owners.id"))
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    amount: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    currency: Mapped[Currency] = mapped_column(Enum(Currency, name="currency_enum", values_callable=_enum_values), nullable=False)
    due_date: Mapped[date] = mapped_column(Date, nullable=False)
    primary_tag: Mapped[str | None] = mapped_column(String(64))
    extra_tags: Mapped[list | None] = mapped_column(JSON, default=list)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="planned")
    note: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)
    linked_transaction_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("transactions.id"))


class BalanceSnapshot(Base):
    """Manual balance checkpoint for an account.

    Stores what the user reports as the current actual balance.
    There is no automatic expected-balance computation — account transaction
    attribution is too sparse for that to be reliable at this stage.
    Delta is computed between consecutive snapshots for the same account.
    """
    __tablename__ = "balance_snapshots"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    account_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("accounts.id"), nullable=False, index=True)
    household_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("households.id"), nullable=False, index=True)
    actual_balance: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    note: Mapped[str | None] = mapped_column(String(255))
    created_by_user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)


class EventLog(Base):
    __tablename__ = "event_log"
    __table_args__ = (Index("ix_event_log_created_event", "created_at", "event_type"),)
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    household_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("households.id"))
    user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    event_type: Mapped[str] = mapped_column(String(128), nullable=False)
    entity_type: Mapped[str | None] = mapped_column(String(64))
    entity_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    payload: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    severity: Mapped[str] = mapped_column(String(16), default="info")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)


class MerchantTagRule(Base):
    """Auto-categorization rule: merchant pattern -> tag. Per household."""
    __tablename__ = "merchant_tag_rules"
    __table_args__ = (
        Index("ix_merchant_tag_rules_household_merchant", "household_id", "merchant_pattern", unique=True),
    )
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    household_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("households.id"), nullable=False)
    merchant_pattern: Mapped[str] = mapped_column(String(255), nullable=False)
    tag: Mapped[str] = mapped_column(String(64), nullable=False)
    source: Mapped[str] = mapped_column(String(32), default="auto")
    hit_count: Mapped[int] = mapped_column(default=0)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc, onupdate=now_utc)


class Debt(Base):
    """Tracks money lent or borrowed. direction='i_owe' or 'they_owe'."""
    __tablename__ = "debts"
    __table_args__ = (
        Index("ix_debts_household_id", "household_id"),
        Index("ix_debts_settled_at", "settled_at"),
    )
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    household_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("households.id"), nullable=False)
    counterparty_name: Mapped[str] = mapped_column(String(255), nullable=False)
    amount: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    currency: Mapped[str] = mapped_column(String(10), nullable=False, default="RUB")
    direction: Mapped[str] = mapped_column(String(20), nullable=False)  # 'i_owe' or 'they_owe'
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)
    due_date: Mapped[date | None] = mapped_column(Date)
    settled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    linked_transaction_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("transactions.id"))
    notes: Mapped[str | None] = mapped_column(Text)


class CategoryBudget(Base):
    """Monthly budget limit per category per household."""
    __tablename__ = "category_budgets"
    __table_args__ = (
        Index("ix_category_budgets_household_month", "household_id", "month_key"),
    )
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    household_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("households.id"), nullable=False)
    month_key: Mapped[str] = mapped_column(String(7), nullable=False)  # '2026-03'
    category_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("finance_categories.id"))
    limit_amount: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    currency: Mapped[str] = mapped_column(String(10), nullable=False, default="RUB")
    rollover_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    rollover_amount: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False, default=Decimal("0"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)


class TagBudget(Base):
    """Monthly budget limit per tag per household."""
    __tablename__ = "tag_budgets"
    __table_args__ = (
        Index("ix_tag_budgets_household_month", "household_id", "month_key"),
        UniqueConstraint("household_id", "month_key", "tag", name="uq_tag_budgets_household_month_tag"),
    )
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    household_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("households.id"), nullable=False)
    month_key: Mapped[str] = mapped_column(String(7), nullable=False)  # '2026-03'
    tag: Mapped[str] = mapped_column(String(255), nullable=False)
    limit_amount: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    currency: Mapped[str] = mapped_column(String(10), nullable=False, default="RUB")
    rollover_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    rollover_amount: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False, default=Decimal("0"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)


class FxRate(Base):
    """Daily FX rate snapshot fetched from exchangerate-api.com."""
    __tablename__ = "fx_rates"
    __table_args__ = (
        UniqueConstraint("date", "from_currency", "to_currency", name="uq_fx_rates_date_from_to"),
    )
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    from_currency: Mapped[str] = mapped_column(String(10), nullable=False)
    to_currency: Mapped[str] = mapped_column(String(10), nullable=False)
    rate: Mapped[Decimal] = mapped_column(Numeric(18, 6), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)
