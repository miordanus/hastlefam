"""
spoilage_service.py — simple rule-based spoilage risk (spec §14, no ML).

risk(age) for an item with a known shelf life:
  age > shelf_life * 0.7  → "warn"  (скоро надо съесть)
  age >= shelf_life       → "spoil_risk"
Shelf life comes from the product row, falling back to a per-category default.
`now` is injectable so tests are deterministic.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime, timezone

from app.domain.enums import FoodCategory, InventoryStatus
from app.infrastructure.db.models import FoodProduct, InventoryItem

WARN = "warn"
SPOIL_RISK = "spoil_risk"

# Per-category shelf-life defaults in days (spec §14). None = effectively long-lived.
SHELF_LIFE_DEFAULTS = {
    FoodCategory.READY_FOOD.value: 2,
    FoodCategory.DAIRY.value: 7,
    FoodCategory.PROTEIN.value: 3,
    FoodCategory.MEAT.value: 2,
    FoodCategory.FISH.value: 2,
    FoodCategory.EGGS.value: 21,
    FoodCategory.VEGETABLES.value: 7,
    FoodCategory.FRUITS.value: 3,
    FoodCategory.BREAD.value: 4,
    FoodCategory.GRAINS.value: 365,
    FoodCategory.PASTA.value: 365,
    FoodCategory.CANNED.value: 730,
    FoodCategory.SAUCES.value: 180,
    FoodCategory.SPICES.value: 730,
    FoodCategory.COFFEE_TEA.value: 365,
    FoodCategory.FROZEN.value: 180,
    FoodCategory.SNACKS.value: 90,
}

# Statuses that mean the item is no longer present → never at risk.
_GONE = {InventoryStatus.OUT.value}


@dataclass
class RiskRow:
    name: str
    level: str          # WARN | SPOIL_RISK
    age_days: float
    shelf_life_days: int


def _now() -> datetime:
    return datetime.now(timezone.utc)


def shelf_life_for(product: FoodProduct) -> int | None:
    if product.shelf_life_days is not None:
        return product.shelf_life_days
    return SHELF_LIFE_DEFAULTS.get(product.category)


def _risk_level(age_days: float, shelf_life: int) -> str | None:
    if age_days >= shelf_life:
        return SPOIL_RISK
    if age_days > shelf_life * 0.7:
        return WARN
    return None


def at_risk(db, household_id: uuid.UUID, now: datetime | None = None) -> list[RiskRow]:
    """Inventory items whose age since last_confirmed_at puts them at risk."""
    now = now or _now()
    rows: list[RiskRow] = []
    pairs = (
        db.query(InventoryItem, FoodProduct)
        .join(FoodProduct, FoodProduct.id == InventoryItem.product_id)
        .filter(InventoryItem.household_id == household_id)
        .all()
    )
    for item, product in pairs:
        if item.status in _GONE or item.last_confirmed_at is None:
            continue
        shelf = shelf_life_for(product)
        if not shelf:
            continue
        confirmed = item.last_confirmed_at
        if confirmed.tzinfo is None:  # SQLite returns naive datetimes
            confirmed = confirmed.replace(tzinfo=timezone.utc)
        age_days = (now - confirmed).total_seconds() / 86400.0
        level = _risk_level(age_days, shelf)
        if level:
            rows.append(RiskRow(product.canonical_name, level, round(age_days, 1), shelf))
    # spoil_risk before warn, then oldest first
    rows.sort(key=lambda r: (r.level != SPOIL_RISK, -r.age_days))
    return rows
