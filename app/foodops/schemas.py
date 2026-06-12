"""
schemas.py — application-layer shapes for FoodOps parsing.

FoodAction is the normalized, validated result the parser hands to the services.
It mirrors one entry of the LLM's {actions: [...]} output (spec §10).
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Optional

from app.domain.enums import FoodIntent


@dataclass
class FoodAction:
    intent: FoodIntent
    product: str
    status: Optional[str] = None        # InventoryStatus value (update_inventory)
    quantity: Optional[Decimal] = None
    unit: Optional[str] = None
    location: Optional[str] = None       # ItemLocation value
    reason: Optional[str] = None         # ShoppingReason value (add_to_shopping_list)
    category: Optional[str] = None       # FoodCategory value, if the LLM inferred one
    confidence: str = "medium"           # Confidence value
