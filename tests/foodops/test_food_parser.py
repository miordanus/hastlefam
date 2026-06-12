import pytest

from app.application.services.llm_service import LLMService
from app.domain.enums import FoodIntent
from app.foodops.parsers import food_parser


class FakeProvider:
    """Returns a canned JSON payload, mimicking the LLM (spec §10 example)."""
    def __init__(self, payload):
        self.payload = payload

    async def generate_json(self, *, system_prompt, user_prompt, schema):
        return self.payload


SPEC_PAYLOAD = {
    "actions": [
        {"intent": "update_inventory", "product": "молоко", "status": "almost_out", "location": "fridge", "confidence": "high"},
        {"intent": "update_inventory", "product": "яйца", "status": "in_stock", "quantity": 4, "unit": "pcs", "location": "fridge", "confidence": "high"},
        {"intent": "update_inventory", "product": "кофе", "status": "out", "location": "shelf", "confidence": "high"},
        {"intent": "discard", "product": "йогурт", "confidence": "high"},
        {"intent": "add_to_shopping_list", "product": "курица", "reason": "manual_request", "confidence": "high"},
        {"intent": "add_to_shopping_list", "product": "сыр", "reason": "manual_request", "confidence": "high"},
        {"intent": "mark_check_needed", "product": "помидоры", "location": "fridge", "confidence": "high"},
    ]
}


@pytest.mark.asyncio
async def test_parses_multi_action_message():
    service = LLMService(FakeProvider(SPEC_PAYLOAD))
    result = await food_parser.parse("длинное сообщение", service=service)
    assert result.ok
    assert len(result.actions) == 7
    by_intent = [a.intent for a in result.actions]
    assert by_intent.count(FoodIntent.UPDATE_INVENTORY) == 3
    assert by_intent.count(FoodIntent.ADD_TO_SHOPPING_LIST) == 2
    eggs = next(a for a in result.actions if a.product == "яйца")
    assert str(eggs.quantity) == "4"
    assert eggs.unit == "pcs"


@pytest.mark.asyncio
async def test_drops_unknown_intents_and_empty_products():
    payload = {"actions": [
        {"intent": "make_dinner", "product": "паста"},      # unknown intent
        {"intent": "discard", "product": ""},                # empty product
        {"intent": "discard", "product": "уксус"},           # valid
    ]}
    service = LLMService(FakeProvider(payload))
    result = await food_parser.parse("x", service=service)
    assert result.ok
    assert len(result.actions) == 1
    assert result.actions[0].product == "уксус"


@pytest.mark.asyncio
async def test_validation_failure_returns_not_ok():
    service = LLMService(FakeProvider({"wrong": "shape"}))
    result = await food_parser.parse("x", service=service)
    assert result.ok is False
    assert result.error
