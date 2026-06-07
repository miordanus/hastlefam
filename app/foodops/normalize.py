"""
normalize.py — canonical product resolution.

Maps a free-text product name to a row in food_products, creating it on first
sight. MVP normalization is intentionally light: lowercase + collapse whitespace.
Real ontology/synonyms come later (spec non-goal: "perfect product ontology").
"""
from __future__ import annotations

import re

from app.domain.enums import FoodCategory
from app.infrastructure.db.models import FoodProduct


def canonicalize(name: str) -> str:
    """Normalize a raw product name to its canonical form."""
    return re.sub(r"\s+", " ", name.strip().lower())


def get_or_create_product(db, name: str, category: str | None = None) -> FoodProduct:
    """Return the FoodProduct for `name`, creating it if absent.

    `db` is a SQLAlchemy session. The caller owns the transaction (flush only,
    no commit) so this composes inside the per-message apply loop.
    """
    canonical = canonicalize(name)
    product = db.query(FoodProduct).filter(FoodProduct.canonical_name == canonical).first()
    if product is None:
        product = FoodProduct(
            canonical_name=canonical,
            category=category or FoodCategory.UNKNOWN.value,
        )
        db.add(product)
        db.flush()
    elif category and product.category == FoodCategory.UNKNOWN.value:
        # Upgrade an unknown category once the LLM gives us a better guess.
        product.category = category
        db.flush()
    return product
