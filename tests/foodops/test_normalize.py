from app.foodops.normalize import canonicalize, get_or_create_product
from app.domain.enums import FoodCategory


def test_canonicalize_lowercases_and_collapses_space():
    assert canonicalize("  Кофе   Молотый ") == "кофе молотый"


def test_get_or_create_is_idempotent(db):
    a = get_or_create_product(db, "Кофе")
    b = get_or_create_product(db, "кофе")
    assert a.id == b.id
    assert db.query(type(a)).count() == 1


def test_unknown_category_upgrades(db):
    p = get_or_create_product(db, "молоко")
    assert p.category == FoodCategory.UNKNOWN.value
    p2 = get_or_create_product(db, "Молоко", category=FoodCategory.DAIRY.value)
    assert p.id == p2.id
    assert p2.category == FoodCategory.DAIRY.value
