"""
inventory_service.py — apply parsed FoodActions to inventory state + history.

Every action appends an immutable inventory_event and (where relevant) upserts
the current inventory_items row. Inventory changes that imply a need to buy
(out / almost_out) auto-add to the shopping list, matching the spec §24 example
where "молоко почти закончилось" and "кофе закончилось" land on the list.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal

from app.domain.enums import (
    Confidence,
    FoodIntent,
    InventoryEventType,
    InventoryStatus,
    ItemLocation,
    ShoppingPriority,
    ShoppingReason,
)
from app.foodops import normalize
from app.foodops.schemas import FoodAction
from app.foodops.services import shopping_service
from app.infrastructure.db.models import InventoryEvent, InventoryItem


def _now() -> datetime:
    return datetime.now(timezone.utc)


@dataclass
class UpdatedItem:
    name: str
    status: str
    quantity: Decimal | None = None
    unit: str | None = None


@dataclass
class ApplyResult:
    """Structured summary for the confirmation reply (spec §24)."""
    updated: list[UpdatedItem] = field(default_factory=list)
    discarded: list[str] = field(default_factory=list)
    added_to_list: list[tuple[str, str]] = field(default_factory=list)  # (product, reason)
    check_needed: list[str] = field(default_factory=list)

    @property
    def total(self) -> int:
        return len(self.updated) + len(self.discarded) + len(self.added_to_list) + len(self.check_needed)


# Inventory status → (shopping reason, priority) for auto-add. None = don't add.
_AUTO_ADD = {
    InventoryStatus.OUT.value: (ShoppingReason.OUT_OF_STOCK.value, ShoppingPriority.HIGH.value),
    InventoryStatus.ALMOST_OUT.value: (ShoppingReason.ALMOST_OUT.value, ShoppingPriority.NORMAL.value),
}


def _upsert_inventory(
    db,
    household_id: uuid.UUID,
    product_id: uuid.UUID,
    location: str,
    status: str,
    quantity: Decimal | None,
    unit: str | None,
    confidence: str,
) -> InventoryItem:
    item = (
        db.query(InventoryItem)
        .filter(
            InventoryItem.household_id == household_id,
            InventoryItem.product_id == product_id,
            InventoryItem.location == location,
        )
        .first()
    )
    if item is None:
        item = InventoryItem(
            household_id=household_id,
            product_id=product_id,
            location=location,
        )
        db.add(item)
    item.status = status
    if quantity is not None:
        item.quantity = quantity
    if unit is not None:
        item.unit = unit
    item.confidence = confidence
    item.last_confirmed_at = _now()
    db.flush()
    return item


def _add_event(db, household_id, user_id, product_id, action, event_type, status, location, raw_input_id, source):
    db.add(InventoryEvent(
        household_id=household_id,
        user_id=user_id,
        product_id=product_id,
        raw_product_name=normalize.canonicalize(action.product),
        event_type=event_type,
        quantity=action.quantity,
        unit=action.unit,
        status=status,
        location=location,
        source=source,
        raw_input_id=raw_input_id,
        confidence=action.confidence or Confidence.MEDIUM.value,
        happened_at=_now(),
    ))
    db.flush()


def apply_action(
    db,
    household_id: uuid.UUID,
    user_id: uuid.UUID | None,
    action: FoodAction,
    result: ApplyResult,
    *,
    raw_input_id: uuid.UUID | None = None,
    source: str = "text",
) -> None:
    location = action.location or ItemLocation.UNKNOWN.value
    confidence = action.confidence or Confidence.MEDIUM.value

    if action.intent == FoodIntent.UPDATE_INVENTORY:
        product = normalize.get_or_create_product(db, action.product, category=action.category)
        status = action.status or InventoryStatus.IN_STOCK.value
        _upsert_inventory(db, household_id, product.id, location, status, action.quantity, action.unit, confidence)
        _add_event(db, household_id, user_id, product.id, action,
                   InventoryEventType.MANUAL_COUNT.value, status, location, raw_input_id, source)
        result.updated.append(UpdatedItem(product.canonical_name, status, action.quantity, action.unit))
        # Auto-add to the shopping list when stock is gone or nearly gone.
        auto = _AUTO_ADD.get(status)
        if auto:
            reason, priority = auto
            shopping_service.add_item(db, household_id, action.product, reason=reason,
                                      priority=priority, source="system", category=action.category)
            result.added_to_list.append((product.canonical_name, reason))

    elif action.intent == FoodIntent.DISCARD:
        product = normalize.get_or_create_product(db, action.product, category=action.category)
        _upsert_inventory(db, household_id, product.id, location, InventoryStatus.OUT.value, None, None, confidence)
        _add_event(db, household_id, user_id, product.id, action,
                   InventoryEventType.DISCARDED.value, InventoryStatus.OUT.value, location, raw_input_id, source)
        result.discarded.append(product.canonical_name)

    elif action.intent == FoodIntent.MARK_CHECK_NEEDED:
        product = normalize.get_or_create_product(db, action.product, category=action.category)
        _upsert_inventory(db, household_id, product.id, location, InventoryStatus.CHECK.value, None, None, confidence)
        _add_event(db, household_id, user_id, product.id, action,
                   InventoryEventType.CHECK_NEEDED.value, InventoryStatus.CHECK.value, location, raw_input_id, source)
        result.check_needed.append(product.canonical_name)

    elif action.intent == FoodIntent.ADD_TO_SHOPPING_LIST:
        reason = action.reason or ShoppingReason.MANUAL_REQUEST.value
        item, _ = shopping_service.add_item(db, household_id, action.product, reason=reason,
                                            source=source, created_by=user_id, category=action.category)
        product_id = item.product_id
        _add_event(db, household_id, user_id, product_id, action,
                   InventoryEventType.ADDED_TO_LIST.value, None, location, raw_input_id, source)
        # Use canonical name for the summary.
        name = normalize.canonicalize(action.product)
        result.added_to_list.append((name, reason))


def apply_actions(
    db,
    household_id: uuid.UUID,
    user_id: uuid.UUID | None,
    actions: list[FoodAction],
    *,
    raw_input_id: uuid.UUID | None = None,
    source: str = "text",
) -> ApplyResult:
    result = ApplyResult()
    for action in actions:
        apply_action(db, household_id, user_id, action, result,
                     raw_input_id=raw_input_id, source=source)
    return result
