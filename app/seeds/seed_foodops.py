"""
seed_foodops.py — baseline canonical products for FoodOps Home (spec §18).

food_products is a global (household-agnostic) vocabulary, so household_id is
accepted only for signature parity with the other seeds. Idempotent: skips a
product that already exists by canonical_name.

shelf_life_days follow the spec §14 defaults; is_always_in_stock marks the
household baseline the product should help keep in stock.
"""
import uuid

from sqlalchemy import text

from app.domain.enums import FoodCategory, InventoryStatus
from app.infrastructure.db.base import DB_SCHEMA

_C = FoodCategory

# (canonical_name, category, default_unit, shelf_life_days, is_always_in_stock, min_stock_status)
PRODUCTS = [
    ("кофе",                _C.COFFEE_TEA, "pack",   None, True,  InventoryStatus.ALMOST_OUT.value),
    ("яйца",                _C.EGGS,       "pcs",    21,   True,  InventoryStatus.LOW.value),
    ("молоко",              _C.DAIRY,      "l",      7,    True,  InventoryStatus.ALMOST_OUT.value),
    ("сыр",                 _C.DAIRY,      "pack",   14,   True,  None),
    ("йогурт",              _C.DAIRY,      "pcs",    7,    False, None),
    ("творог",              _C.DAIRY,      "pack",   7,    False, None),
    ("курица",              _C.MEAT,       "pack",   2,    False, None),
    ("замороженный белок",  _C.FROZEN,     "pack",   180,  True,  None),
    ("хлеб",                _C.BREAD,      "pcs",    4,    True,  None),
    ("масло растительное",  _C.SAUCES,     "bottle", 365,  True,  None),
    ("овощи",               _C.VEGETABLES, "pack",   7,    True,  None),
    ("помидоры",            _C.VEGETABLES, "pcs",    5,    False, None),
    ("бананы",              _C.FRUITS,     "pcs",    5,    False, None),
    ("готовая еда",         _C.READY_FOOD, "box",    2,    False, None),
]


def run(db, household_id=None):
    for name, category, unit, shelf_life, always, min_status in PRODUCTS:
        exists = db.execute(
            text(f"SELECT 1 FROM {DB_SCHEMA}.food_products WHERE canonical_name = :n LIMIT 1"),
            {"n": name},
        ).scalar()
        if exists:
            continue
        db.execute(
            text(
                f"INSERT INTO {DB_SCHEMA}.food_products "
                "(id, canonical_name, category, default_unit, shelf_life_days, is_always_in_stock, min_stock_status, created_at) "
                "VALUES (:id, :n, :cat, :unit, :sl, :always, :mins, now())"
            ),
            {
                "id": uuid.uuid4(),
                "n": name,
                "cat": category.value,
                "unit": unit,
                "sl": shelf_life,
                "always": always,
                "mins": min_status,
            },
        )
    db.commit()
