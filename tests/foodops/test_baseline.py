from app.domain.enums import ShoppingReason, ShoppingStatus
from app.foodops import handle
from app.foodops.services import baseline_service
from app.infrastructure.db.models import FoodProduct, InventoryItem, ShoppingListItem


def _product(db, name, *, always, category="unknown"):
    p = FoodProduct(canonical_name=name, category=category, is_always_in_stock=always)
    db.add(p); db.flush()
    return p


def _inv(db, hid, product, status):
    db.add(InventoryItem(household_id=hid, product_id=product.id, location="fridge", status=status))
    db.flush()


def test_ensure_baseline_adds_missing_and_low(db, household):
    hid, _ = household
    coffee = _product(db, "кофе", always=True)          # no inventory → missing
    milk = _product(db, "молоко", always=True)
    _inv(db, hid, milk, "out")                            # out → high
    cheese = _product(db, "сыр", always=True)
    _inv(db, hid, cheese, "in_stock")                     # present → skip
    toma = _product(db, "помидоры", always=False)
    _inv(db, hid, toma, "out")                            # not baseline → ignored

    added = baseline_service.ensure_baseline_on_list(db, hid)
    assert set(added) == {"кофе", "молоко"}

    open_items = db.query(ShoppingListItem).filter(
        ShoppingListItem.status == ShoppingStatus.OPEN.value).all()
    by_name = {db.get(FoodProduct, i.product_id).canonical_name: i for i in open_items}
    assert by_name["кофе"].reason == ShoppingReason.MIN_STOCK.value
    assert by_name["молоко"].priority == "high"   # out
    assert by_name["кофе"].priority == "normal"   # missing
    assert "сыр" not in by_name
    assert "помидоры" not in by_name


def test_ensure_baseline_is_idempotent(db, household):
    hid, _ = household
    _product(db, "кофе", always=True)
    baseline_service.ensure_baseline_on_list(db, hid)
    baseline_service.ensure_baseline_on_list(db, hid)
    rows = db.query(ShoppingListItem).filter(
        ShoppingListItem.status == ShoppingStatus.OPEN.value).all()
    assert len(rows) == 1


async def test_buy_query_shows_baseline_section(db, household):
    hid, uid = household
    _product(db, "кофе", always=True)   # missing baseline
    reply = await handle.handle_message(db, hid, uid, "что купить?", parse_service=None)
    assert "База (держим всегда дома):" in reply
    assert "кофе" in reply
