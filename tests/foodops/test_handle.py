from app.application.services.llm_service import LLMService
from app.domain.enums import ParsingStatus
from app.foodops import handle
from app.infrastructure.db.models import RawInput
from tests.foodops.test_food_parser import SPEC_PAYLOAD, FakeProvider

SPEC_MESSAGE = (
    "В холодильнике молоко почти закончилось, яйца 4 штуки, кофе закончился, "
    "йогурт выкинул, добавь курицу и сыр в список, помидоры надо проверить."
)


async def test_full_flow_confirmation_and_buy_query(db, household):
    hid, uid = household
    service = LLMService(FakeProvider(SPEC_PAYLOAD))

    reply = await handle.handle_message(db, hid, uid, SPEC_MESSAGE, parse_service=service)

    # Confirmation reply (spec §24)
    assert "Ок, обновил." in reply
    assert "яйца — 4 шт" in reply
    assert "кофе — закончилось" in reply
    assert "- йогурт — выкинуто" in reply
    assert "Надо проверить:" in reply
    assert "помидоры" in reply

    # raw_inputs persisted + parsed
    raws = db.query(RawInput).all()
    assert len(raws) == 1
    assert raws[0].parsing_status == ParsingStatus.PARSED.value
    assert raws[0].parsed_json["actions"][0]["product"] == "молоко"

    # "что купить?" answered from the list, no LLM needed
    buy = await handle.handle_message(db, hid, uid, "что купить?", parse_service=None)
    assert "Срочно:" in buy
    assert "кофе — закончился" in buy
    for name in ("молоко", "курица", "сыр"):
        assert name in buy
    assert "йогурт" not in buy


async def test_unparseable_message_marks_needs_review(db, household):
    hid, uid = household
    service = LLMService(FakeProvider({"bad": "shape"}))
    reply = await handle.handle_message(db, hid, uid, "бла бла", parse_service=service)
    assert reply == handle.replies.PARSE_FAILED
    raw = db.query(RawInput).one()
    assert raw.parsing_status == ParsingStatus.NEEDS_REVIEW.value
