"""
food_parser.py — LLM multi-action parser for free-text grocery messages.

Splits one message (often many updates at once) into structured FoodActions,
per spec §10. Pure of DB/Telegram: takes text, returns a FoodParseResult.
Reuses the existing LLMService contract+validation layer.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation

from app.application.services.llm_service import LLMService, LLMContractFailure
from app.domain.enums import FoodIntent
from app.foodops.schemas import FoodAction
from app.infrastructure.llm.openai_client import OpenAIProvider

SYSTEM_PROMPT = (
    "Ты парсер домашнего учёта продуктов. Пользователь пишет одно сообщение, "
    "в котором может быть сразу много обновлений по холодильнику, полкам и списку покупок. "
    "Разбей сообщение на отдельные действия. Не выдумывай продукты и факты.\n\n"
    "Возможные intent:\n"
    "- update_inventory — продукт есть/мало/почти закончился/закончился. status: "
    "in_stock|low|almost_out|out. Если названо количество — quantity и unit (pcs/шт и т.п.).\n"
    "- discard — продукт выкинули/испортился.\n"
    "- add_to_shopping_list — явно просят добавить в список (reason: manual_request).\n"
    "- mark_check_needed — продукт под вопросом, надо проверить (status: check).\n\n"
    "location: fridge|freezer|shelf|unknown (по контексту). confidence: low|medium|high.\n"
    "Верни строго JSON по схеме {\"actions\": [...]}. Если действий нет — пустой список."
)

FOOD_PARSE_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "actions": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "intent": {"type": "string"},
                    "product": {"type": "string"},
                    "status": {"type": ["string", "null"]},
                    "quantity": {"type": ["number", "null"]},
                    "unit": {"type": ["string", "null"]},
                    "location": {"type": ["string", "null"]},
                    "reason": {"type": ["string", "null"]},
                    "category": {"type": ["string", "null"]},
                    "confidence": {"type": "string"},
                },
                "required": ["intent", "product"],
            },
        }
    },
    "required": ["actions"],
}

_VALID_INTENTS = {i.value for i in FoodIntent}


@dataclass
class FoodParseResult:
    ok: bool
    actions: list[FoodAction] = field(default_factory=list)
    error: str | None = None


def _to_decimal(value) -> Decimal | None:
    if value is None:
        return None
    try:
        d = Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None
    # Whole numbers (eggs=4.0) collapse to 4; fractions stay as-is. Avoid
    # Decimal.normalize() which would render e.g. 10 as 1E+1.
    if d == d.to_integral_value():
        return d.to_integral_value()
    return d


def _to_action(item) -> FoodAction | None:
    """Map one validated FoodActionItem to a FoodAction; drop unknown intents."""
    intent = (item.intent or "").strip()
    if intent not in _VALID_INTENTS:
        return None
    product = (item.product or "").strip()
    if not product:
        return None
    return FoodAction(
        intent=FoodIntent(intent),
        product=product,
        status=item.status,
        quantity=_to_decimal(item.quantity),
        unit=item.unit,
        location=item.location,
        reason=item.reason,
        category=item.category,
        confidence=item.confidence or "medium",
    )


async def parse(text: str, service: LLMService | None = None) -> FoodParseResult:
    """Parse a free-text grocery message into FoodActions.

    `service` is injectable for tests; defaults to the shared OpenAI provider.
    """
    if service is None:
        service = LLMService(OpenAIProvider())
    result = await service.run_contract("food_parse", SYSTEM_PROMPT, text, FOOD_PARSE_SCHEMA)
    if isinstance(result, LLMContractFailure):
        return FoodParseResult(ok=False, error=result.error)
    actions = [a for a in (_to_action(i) for i in result.actions) if a is not None]
    return FoodParseResult(ok=True, actions=actions)
