from datetime import datetime, timedelta, timezone

from app.foodops import handle, revision
from app.foodops.services import spoilage_service
from app.infrastructure.db.models import FoodProduct, InventoryItem, RawInput

NOW = datetime(2026, 6, 7, 12, 0, tzinfo=timezone.utc)


# ── revision (single-shot) ───────────────────────────────────────────────────

def test_detect_area():
    assert revision.detect_area("проведи ревизию холодильника") == revision.FRIDGE
    assert revision.detect_area("ревизия полок") == revision.SHELVES
    assert revision.detect_area("проведи ревизию морозилки") == revision.FREEZER
    assert revision.detect_area("молоко закончилось") is None


async def test_revision_returns_prompt_without_llm(db, household):
    hid, uid = household
    # parse_service=None would crash if it tried to hit the LLM — proves no parse.
    reply = await handle.handle_message(db, hid, uid, "проведи ревизию холодильника", parse_service=None)
    assert "идём по холодильнику" in reply.lower()
    assert "молочка" in reply.lower()
    assert db.query(RawInput).one().parsing_status == "parsed"


# ── spoilage ─────────────────────────────────────────────────────────────────

def _stock(db, hid, name, category, shelf_life, confirmed_days_ago, *, status="in_stock"):
    p = FoodProduct(canonical_name=name, category=category, shelf_life_days=shelf_life)
    db.add(p)
    db.flush()
    db.add(InventoryItem(
        household_id=hid, product_id=p.id, location="fridge", status=status,
        last_confirmed_at=NOW - timedelta(days=confirmed_days_ago),
    ))
    db.flush()
    return p


def test_at_risk_thresholds(db, household):
    hid, uid = household
    _stock(db, hid, "молоко", "dairy", 7, confirmed_days_ago=8)   # past shelf life → spoil_risk
    _stock(db, hid, "сыр", "dairy", 14, confirmed_days_ago=11)    # >70% → warn
    _stock(db, hid, "яйца", "eggs", 21, confirmed_days_ago=2)     # fresh → none
    _stock(db, hid, "кофе", "coffee_tea", 5, confirmed_days_ago=99, status="out")  # gone → skip

    rows = spoilage_service.at_risk(db, hid, now=NOW)
    by_name = {r.name: r.level for r in rows}
    assert by_name["молоко"] == spoilage_service.SPOIL_RISK
    assert by_name["сыр"] == spoilage_service.WARN
    assert "яйца" not in by_name
    assert "кофе" not in by_name
    # spoil_risk sorts before warn
    assert rows[0].name == "молоко"


async def test_spoilage_query_through_handle(db, household):
    hid, uid = household
    _stock(db, hid, "помидоры", "vegetables", 5, confirmed_days_ago=6)
    reply = await handle.handle_message(db, hid, uid, "что скоро испортится?", parse_service=None)
    assert "Риск порчи:" in reply
    assert "помидоры" in reply


def test_shelf_life_falls_back_to_category_default(db, household):
    hid, _ = household
    p = FoodProduct(canonical_name="готовая еда", category="ready_food", shelf_life_days=None)
    db.add(p); db.flush()
    assert spoilage_service.shelf_life_for(p) == spoilage_service.SHELF_LIFE_DEFAULTS["ready_food"]
