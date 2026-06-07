import pytest

from app.application.services.llm_service import LLMService
from app.domain.enums import FoodCategory, FoodIntent
from app.foodops import handle
from app.foodops.parsers import food_parser
from app.foodops.parsers.stub_parser import StubProvider
from app.seeds import seed_foodops

SPEC_MESSAGE = (
    "В холодильнике молоко почти закончилось, яйца 4 штуки, кофе закончился, "
    "йогурт выкинул, добавь курицу и сыр в список, помидоры надо проверить."
)


# ── stub parser (offline) ────────────────────────────────────────────────────

async def test_stub_parses_spec_message_intents():
    result = await food_parser.parse(SPEC_MESSAGE, service=LLMService(StubProvider()))
    assert result.ok
    intents = [a.intent for a in result.actions]
    assert intents.count(FoodIntent.UPDATE_INVENTORY) == 3   # молоко, яйца, кофе
    assert intents.count(FoodIntent.ADD_TO_SHOPPING_LIST) == 2  # курицу, сыр (split on "и")
    assert intents.count(FoodIntent.DISCARD) == 1            # йогурт
    assert intents.count(FoodIntent.MARK_CHECK_NEEDED) == 1  # помидоры
    coffee = next(a for a in result.actions if "кофе" in a.product)
    assert coffee.status == "out"


async def test_stub_end_to_end_through_handle(db, household):
    hid, uid = household
    reply = await handle.handle_message(db, hid, uid, SPEC_MESSAGE, parse_service=LLMService(StubProvider()))
    assert "Ок, обновил." in reply
    buy = await handle.handle_message(db, hid, uid, "что купить?", parse_service=LLMService(StubProvider()))
    assert "кофе" in buy  # out → auto-added, urgent


# ── seed metadata ────────────────────────────────────────────────────────────

def test_seed_products_are_valid_and_unique():
    names = [p[0] for p in seed_foodops.PRODUCTS]
    assert len(names) == len(set(names))  # unique canonical names
    valid = {c.value for c in FoodCategory}
    assert all(p[1].value in valid for p in seed_foodops.PRODUCTS)
    baseline = [p[0] for p in seed_foodops.PRODUCTS if p[4]]
    assert {"кофе", "яйца", "молоко"} <= set(baseline)
