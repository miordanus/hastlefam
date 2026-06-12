"""
food_models.py — FoodOps Home ORM models.

Kept separate from all_models.py to keep the finance domain readable. Imported by
the models package __init__ so SQLAlchemy metadata (and the SQLite test schema)
registers these tables on Base.

Status/category/enum-like fields are stored as plain String columns (forgiving,
no PG enum types). Valid values live in app.domain.enums.
"""
import uuid
from datetime import date, datetime, timezone
from decimal import Decimal

from sqlalchemy import (
    JSON,
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.infrastructure.db.base import Base


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


class FoodProduct(Base):
    """Canonical normalized product. Global (no household) — shared vocabulary."""
    __tablename__ = "food_products"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    canonical_name: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)
    category: Mapped[str] = mapped_column(String(32), nullable=False, default="unknown")
    default_unit: Mapped[str | None] = mapped_column(String(32))
    shelf_life_days: Mapped[int | None] = mapped_column()
    is_always_in_stock: Mapped[bool] = mapped_column(Boolean, default=False)
    min_stock_status: Mapped[str | None] = mapped_column(String(32))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)


class InventoryItem(Base):
    """Current approximate state per household/product/location."""
    __tablename__ = "inventory_items"
    __table_args__ = (
        UniqueConstraint("household_id", "product_id", "location", name="uq_inventory_household_product_location"),
        Index("ix_inventory_items_household", "household_id"),
    )
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    household_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("households.id"), nullable=False)
    product_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("food_products.id"), nullable=False)
    location: Mapped[str] = mapped_column(String(16), nullable=False, default="unknown")
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="in_stock")
    quantity: Mapped[Decimal | None] = mapped_column(Numeric(12, 3))
    unit: Mapped[str | None] = mapped_column(String(32))
    expires_at: Mapped[date | None] = mapped_column(Date)
    last_confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    confidence: Mapped[str] = mapped_column(String(16), default="medium")
    notes: Mapped[str | None] = mapped_column(Text)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc, onupdate=now_utc)


class InventoryEvent(Base):
    """Append-only history of everything that happened to inventory."""
    __tablename__ = "inventory_events"
    __table_args__ = (
        Index("ix_inventory_events_household_happened", "household_id", "happened_at"),
    )
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    household_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("households.id"), nullable=False)
    user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    product_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("food_products.id"))
    raw_product_name: Mapped[str | None] = mapped_column(String(255))
    event_type: Mapped[str] = mapped_column(String(32), nullable=False)
    quantity: Mapped[Decimal | None] = mapped_column(Numeric(12, 3))
    unit: Mapped[str | None] = mapped_column(String(32))
    status: Mapped[str | None] = mapped_column(String(16))
    location: Mapped[str | None] = mapped_column(String(16))
    happened_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)
    source: Mapped[str] = mapped_column(String(16), default="text")
    raw_input_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("raw_inputs.id"))
    confidence: Mapped[str] = mapped_column(String(16), default="medium")
    notes: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)


class ShoppingListItem(Base):
    """Household-level shopping list. Deduplicated by open product."""
    __tablename__ = "shopping_list_items"
    __table_args__ = (
        Index("ix_shopping_list_household_status", "household_id", "status"),
    )
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    household_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("households.id"), nullable=False)
    product_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("food_products.id"))
    raw_product_name: Mapped[str | None] = mapped_column(String(255))
    quantity: Mapped[Decimal | None] = mapped_column(Numeric(12, 3))
    unit: Mapped[str | None] = mapped_column(String(32))
    priority: Mapped[str] = mapped_column(String(16), default="normal")
    reason: Mapped[str | None] = mapped_column(String(32))
    status: Mapped[str] = mapped_column(String(16), default="open")
    source: Mapped[str] = mapped_column(String(16), default="text")
    created_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc, onupdate=now_utc)


class RawInput(Base):
    """Every user input, stored before parsing."""
    __tablename__ = "raw_inputs"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    household_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("households.id"), nullable=False)
    user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    input_type: Mapped[str] = mapped_column(String(32), default="text")
    raw_text: Mapped[str] = mapped_column(Text, nullable=False)
    parsed_json: Mapped[dict | None] = mapped_column(JSON)
    parsing_status: Mapped[str] = mapped_column(String(16), default="pending")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)


class Receipt(Base):
    """Receipt/order. Modeled early; not written in Milestone 1."""
    __tablename__ = "receipts"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    household_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("households.id"), nullable=False)
    store_name: Mapped[str | None] = mapped_column(String(255))
    purchased_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    source_type: Mapped[str | None] = mapped_column(String(32))
    raw_text: Mapped[str | None] = mapped_column(Text)
    total_amount: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    currency: Mapped[str] = mapped_column(String(8), default="RUB")
    parsing_status: Mapped[str] = mapped_column(String(16), default="pending")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)


class ReceiptItem(Base):
    """Line item of a receipt. Modeled early; not written in Milestone 1."""
    __tablename__ = "receipt_items"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    receipt_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("receipts.id"), nullable=False)
    raw_name: Mapped[str] = mapped_column(String(255), nullable=False)
    product_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("food_products.id"))
    quantity: Mapped[Decimal | None] = mapped_column(Numeric(12, 3))
    unit: Mapped[str | None] = mapped_column(String(32))
    price_total: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    price_per_unit: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    confidence: Mapped[str] = mapped_column(String(16), default="medium")
    needs_review: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)
