"""
baseline_service.py — always-in-stock / min-stock baseline (spec §18).

Products flagged is_always_in_stock should never quietly run out. When such a
product is missing or low/out, ensure it's on the shopping list with
reason=min_stock so "что купить?" surfaces it as part of the home baseline.
"""
from __future__ import annotations

import uuid

from app.domain.enums import (
    InventoryStatus,
    ShoppingPriority,
    ShoppingReason,
)
from app.foodops.services import shopping_service
from app.infrastructure.db.models import FoodProduct, InventoryItem

# A product is considered "present" (no restock needed) if any inventory row has
# one of these statuses. low/almost_out/out — or no row at all — trigger restock.
_PRESENT = {
    InventoryStatus.IN_STOCK.value,
    InventoryStatus.CHECK.value,
    InventoryStatus.SPOIL_RISK.value,
}


def ensure_baseline_on_list(db, household_id: uuid.UUID) -> list[str]:
    """Add missing/low always-in-stock products to the list (reason=min_stock).

    Returns the canonical names added/refreshed. Does not commit.
    """
    added: list[str] = []
    baseline = db.query(FoodProduct).filter(FoodProduct.is_always_in_stock.is_(True)).all()
    for product in baseline:
        statuses = {
            s for (s,) in db.query(InventoryItem.status)
            .filter(
                InventoryItem.household_id == household_id,
                InventoryItem.product_id == product.id,
            )
            .all()
        }
        if statuses & _PRESENT:
            continue  # confidently present somewhere

        priority = (
            ShoppingPriority.HIGH.value
            if InventoryStatus.OUT.value in statuses
            else ShoppingPriority.NORMAL.value
        )
        shopping_service.add_item(
            db,
            household_id,
            product.canonical_name,
            reason=ShoppingReason.MIN_STOCK.value,
            priority=priority,
            source="system",
            category=product.category,
        )
        added.append(product.canonical_name)
    return added
