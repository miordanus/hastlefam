from datetime import datetime, timedelta, timezone

from app.domain.enums import FoodIntent, InventoryEventType
from app.foodops import handle
from app.foodops.schemas import FoodAction
from app.foodops.services import inventory_service, report_service
from app.infrastructure.db.models import FoodProduct, InventoryEvent

NOW = datetime(2026, 6, 7, 12, 0, tzinfo=timezone.utc)


def _discard_event(db, hid, name, category, days_ago):
    p = db.query(FoodProduct).filter(FoodProduct.canonical_name == name).first()
    if p is None:
        p = FoodProduct(canonical_name=name, category=category)
        db.add(p); db.flush()
    db.add(InventoryEvent(
        household_id=hid, product_id=p.id, raw_product_name=name,
        event_type=InventoryEventType.DISCARDED.value,
        happened_at=NOW - timedelta(days=days_ago),
    ))
    db.flush()


def test_waste_summary_windows_and_counts(db, household):
    hid, _ = household
    _discard_event(db, hid, "йогурт", "dairy", 2)
    _discard_event(db, hid, "йогурт", "dairy", 10)     # repeated
    _discard_event(db, hid, "торт", "ready_food", 5)
    _discard_event(db, hid, "уксус", "sauces", 45)      # outside 30d window

    s = report_service.waste_summary(db, hid, window_days=30, now=NOW)
    assert s.total == 3                                  # uxус excluded
    assert dict(s.by_product)["йогурт"] == 2
    assert dict(s.by_category)["dairy"] == 2
    assert s.repeated == [("йогурт", 2)]                 # only count>=2
    # most-discarded first
    assert s.by_product[0][0] == "йогурт"


def test_empty_waste_report_message():
    from app.foodops import replies
    s = report_service.WasteSummary(window_days=30, total=0)
    assert "ничего не выкидывали" in replies.format_waste(s)


async def test_waste_query_through_handle(db, household):
    hid, uid = household
    # Two discards via the real apply path → discarded events exist.
    inventory_service.apply_actions(db, hid, uid, [
        FoodAction(FoodIntent.DISCARD, "йогурт"),
        FoodAction(FoodIntent.DISCARD, "помидоры"),
    ])
    reply = await handle.handle_message(db, hid, uid, "что выкинули?", parse_service=None)
    assert "Отходы за 30 дней: 2 выкинуто" in reply
    assert "йогурт" in reply
