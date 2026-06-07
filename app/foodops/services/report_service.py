"""
report_service.py — waste / risk reporting (spec §13).

Aggregates discarded inventory_events over a window. MVP tracks frequency and
category only (no prices yet); the schema supports adding value later. `now` is
injectable for deterministic tests.
"""
from __future__ import annotations

import uuid
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

from app.domain.enums import InventoryEventType
from app.infrastructure.db.models import FoodProduct, InventoryEvent


@dataclass
class WasteSummary:
    window_days: int
    total: int = 0
    by_category: list[tuple[str, int]] = field(default_factory=list)   # sorted desc
    by_product: list[tuple[str, int]] = field(default_factory=list)    # sorted desc
    repeated: list[tuple[str, int]] = field(default_factory=list)      # count >= 2


def _now() -> datetime:
    return datetime.now(timezone.utc)


def waste_summary(
    db,
    household_id: uuid.UUID,
    window_days: int = 30,
    now: datetime | None = None,
) -> WasteSummary:
    now = now or _now()
    cutoff = now - timedelta(days=window_days)

    pairs = (
        db.query(InventoryEvent, FoodProduct)
        .outerjoin(FoodProduct, FoodProduct.id == InventoryEvent.product_id)
        .filter(
            InventoryEvent.household_id == household_id,
            InventoryEvent.event_type == InventoryEventType.DISCARDED.value,
        )
        .all()
    )

    by_product: Counter = Counter()
    by_category: Counter = Counter()
    for event, product in pairs:
        ts = event.happened_at
        if ts is None:
            continue
        if ts.tzinfo is None:  # SQLite naive datetimes
            ts = ts.replace(tzinfo=timezone.utc)
        if ts < cutoff:
            continue
        name = product.canonical_name if product else (event.raw_product_name or "?")
        category = product.category if product else "unknown"
        by_product[name] += 1
        by_category[category] += 1

    products_sorted = sorted(by_product.items(), key=lambda kv: (-kv[1], kv[0]))
    return WasteSummary(
        window_days=window_days,
        total=sum(by_product.values()),
        by_category=sorted(by_category.items(), key=lambda kv: (-kv[1], kv[0])),
        by_product=products_sorted,
        repeated=[(n, c) for n, c in products_sorted if c >= 2],
    )
