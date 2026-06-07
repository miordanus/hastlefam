"""
shopping_service.py — household shopping list: dedup add + "что купить?" query.

The list is household-level (both members share it). Adding a product that is
already open updates the existing row instead of duplicating it (spec §12).
"""
from __future__ import annotations

import uuid

from app.domain.enums import ShoppingPriority, ShoppingReason, ShoppingStatus
from app.foodops import normalize
from app.infrastructure.db.models import ShoppingListItem

# Higher number = more urgent (for sorting "что купить?").
_PRIORITY_RANK = {
    ShoppingPriority.HIGH.value: 0,
    ShoppingPriority.NORMAL.value: 1,
    ShoppingPriority.LOW.value: 2,
}


def _find_open(db, household_id: uuid.UUID, product_id: uuid.UUID | None, raw_name: str | None):
    q = db.query(ShoppingListItem).filter(
        ShoppingListItem.household_id == household_id,
        ShoppingListItem.status == ShoppingStatus.OPEN.value,
    )
    if product_id is not None:
        return q.filter(ShoppingListItem.product_id == product_id).first()
    return q.filter(ShoppingListItem.raw_product_name == raw_name).first()


def add_item(
    db,
    household_id: uuid.UUID,
    name: str,
    *,
    reason: str = ShoppingReason.MANUAL_REQUEST.value,
    priority: str = ShoppingPriority.NORMAL.value,
    source: str = "text",
    created_by: uuid.UUID | None = None,
    category: str | None = None,
) -> tuple[ShoppingListItem, bool]:
    """Add `name` to the open list, or update the existing open row.

    Returns (item, created). Never commits — caller owns the transaction.
    """
    product = normalize.get_or_create_product(db, name, category=category)
    existing = _find_open(db, household_id, product.id, normalize.canonicalize(name))
    if existing is not None:
        # Merge: keep the most urgent priority, refresh reason if more specific.
        if _PRIORITY_RANK.get(priority, 1) < _PRIORITY_RANK.get(existing.priority, 1):
            existing.priority = priority
        if reason and reason != ShoppingReason.MANUAL_REQUEST.value:
            existing.reason = reason
        elif existing.reason is None:
            existing.reason = reason
        db.flush()
        return existing, False

    item = ShoppingListItem(
        household_id=household_id,
        product_id=product.id,
        raw_product_name=normalize.canonicalize(name),
        priority=priority,
        reason=reason,
        status=ShoppingStatus.OPEN.value,
        source=source,
        created_by=created_by,
    )
    db.add(item)
    db.flush()
    return item, True


def list_to_buy(db, household_id: uuid.UUID) -> list[ShoppingListItem]:
    """Open shopping items, most urgent first (spec §25)."""
    items = (
        db.query(ShoppingListItem)
        .filter(
            ShoppingListItem.household_id == household_id,
            ShoppingListItem.status == ShoppingStatus.OPEN.value,
        )
        .all()
    )
    return sorted(items, key=lambda i: (_PRIORITY_RANK.get(i.priority, 1), i.created_at or 0))
