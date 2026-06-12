"""
handle.py — message orchestration core for FoodOps (framework-agnostic).

Given a DB session + household/user + text, this does the whole Slice-1 loop:
save raw input → answer "что купить?" or parse → apply actions → return reply text.
No aiogram, no commit — the bot wrapper owns the transaction. Fully unit-testable.
"""
from __future__ import annotations

import uuid

from app.domain.enums import ParsingStatus, RawInputType
from app.foodops import queries, replies, revision
from app.foodops.parsers import food_parser
from app.foodops.services import (
    baseline_service,
    inventory_service,
    report_service,
    shopping_service,
    spoilage_service,
)
from app.infrastructure.db.models import RawInput


def _serialize_actions(actions) -> dict:
    return {
        "actions": [
            {
                "intent": a.intent.value,
                "product": a.product,
                "status": a.status,
                "quantity": str(a.quantity) if a.quantity is not None else None,
                "unit": a.unit,
                "location": a.location,
                "reason": a.reason,
                "confidence": a.confidence,
            }
            for a in actions
        ]
    }


async def handle_message(
    db,
    household_id: uuid.UUID,
    user_id: uuid.UUID | None,
    text: str,
    *,
    parse_service=None,
) -> str:
    """Process one inbound message; return the reply text. Does not commit."""
    raw = RawInput(
        household_id=household_id,
        user_id=user_id,
        input_type=RawInputType.TEXT.value,
        raw_text=text,
        parsing_status=ParsingStatus.PENDING.value,
    )
    db.add(raw)
    db.flush()

    # Guided revision trigger — reply with the category checklist (no LLM).
    area = revision.detect_area(text)
    if area is not None:
        raw.parsing_status = ParsingStatus.PARSED.value
        return revision.revision_prompt(area)

    # Read-only "что купить?" — top up the always-in-stock baseline, then list.
    if queries.is_what_to_buy(text):
        raw.parsing_status = ParsingStatus.PARSED.value
        baseline_service.ensure_baseline_on_list(db, household_id)
        items = shopping_service.list_to_buy(db, household_id)
        return replies.format_to_buy(db, items)

    # Read-only "что скоро испортится?" — answer from inventory, no LLM.
    if queries.is_spoilage(text):
        raw.parsing_status = ParsingStatus.PARSED.value
        return replies.format_spoilage(spoilage_service.at_risk(db, household_id))

    # Read-only "что выкинули? / что проёбывается?" — waste report, no LLM.
    if queries.is_waste(text):
        raw.parsing_status = ParsingStatus.PARSED.value
        return replies.format_waste(report_service.waste_summary(db, household_id))

    result = await food_parser.parse(text, service=parse_service)
    if not result.ok:
        raw.parsing_status = ParsingStatus.NEEDS_REVIEW.value
        return replies.PARSE_FAILED

    apply_result = inventory_service.apply_actions(
        db, household_id, user_id, result.actions, raw_input_id=raw.id, source="text"
    )
    raw.parsed_json = _serialize_actions(result.actions)
    raw.parsing_status = ParsingStatus.PARSED.value
    return replies.format_apply(apply_result)
