from decimal import Decimal

from app.domain.enums import FoodIntent, InventoryStatus, ShoppingReason, ShoppingStatus
from app.foodops.schemas import FoodAction
from app.foodops.services import inventory_service, shopping_service
from app.infrastructure.db.models import InventoryEvent, InventoryItem, ShoppingListItem


def _spec_actions():
    return [
        FoodAction(FoodIntent.UPDATE_INVENTORY, "молоко", status="almost_out", location="fridge"),
        FoodAction(FoodIntent.UPDATE_INVENTORY, "яйца", status="in_stock", quantity=Decimal("4"), unit="pcs", location="fridge"),
        FoodAction(FoodIntent.UPDATE_INVENTORY, "кофе", status="out", location="shelf"),
        FoodAction(FoodIntent.DISCARD, "йогурт"),
        FoodAction(FoodIntent.ADD_TO_SHOPPING_LIST, "курица", reason="manual_request"),
        FoodAction(FoodIntent.ADD_TO_SHOPPING_LIST, "сыр", reason="manual_request"),
        FoodAction(FoodIntent.MARK_CHECK_NEEDED, "помидоры", location="fridge"),
    ]


def test_apply_spec_message_updates_state_and_list(db, household):
    hid, uid = household
    result = inventory_service.apply_actions(db, hid, uid, _spec_actions())

    # Inventory state reflects latest statuses
    by_name = {_pname(db, i): i.status for i in db.query(InventoryItem).all()}
    assert by_name["молоко"] == InventoryStatus.ALMOST_OUT.value
    assert by_name["кофе"] == InventoryStatus.OUT.value
    assert by_name["йогурт"] == InventoryStatus.OUT.value
    assert by_name["помидоры"] == InventoryStatus.CHECK.value

    # Eggs quantity preserved
    eggs = next(i for i in db.query(InventoryItem).all() if _pname(db, i) == "яйца")
    assert eggs.quantity == Decimal("4")

    # Shopping list: курица, сыр (manual) + молоко (almost_out) + кофе (out)
    open_items = shopping_service.list_to_buy(db, hid)
    open_names = {_pname(db, i) for i in open_items}
    assert {"курица", "сыр", "молоко", "кофе"} <= open_names
    assert "йогурт" not in open_names  # discard does not add to list

    # кофе (out) is high priority → sorted first
    assert _pname(db, open_items[0]) == "кофе"

    # Events are append-only: one per action
    assert db.query(InventoryEvent).count() == 7

    # Summary structure
    assert ("кофе", ShoppingReason.OUT_OF_STOCK.value) in result.added_to_list
    assert "йогурт" in result.discarded
    assert "помидоры" in result.check_needed


def test_shopping_list_dedups(db, household):
    hid, uid = household
    shopping_service.add_item(db, hid, "молоко")
    shopping_service.add_item(db, hid, "Молоко")  # same canonical, different case
    rows = db.query(ShoppingListItem).filter(ShoppingListItem.status == ShoppingStatus.OPEN.value).all()
    assert len(rows) == 1


def test_out_status_upgrades_existing_list_priority(db, household):
    hid, uid = household
    # Manually added at normal priority...
    shopping_service.add_item(db, hid, "кофе")
    # ...then inventory says it's out → should bump to high + out_of_stock reason
    inventory_service.apply_actions(db, hid, uid, [
        FoodAction(FoodIntent.UPDATE_INVENTORY, "кофе", status="out", location="shelf"),
    ])
    rows = db.query(ShoppingListItem).filter(ShoppingListItem.status == ShoppingStatus.OPEN.value).all()
    assert len(rows) == 1
    assert rows[0].priority == "high"
    assert rows[0].reason == ShoppingReason.OUT_OF_STOCK.value


def _pname(db, inv_or_item):
    """Resolve the canonical product name for an inventory/shopping row."""
    from app.infrastructure.db.models import FoodProduct
    return db.get(FoodProduct, inv_or_item.product_id).canonical_name
