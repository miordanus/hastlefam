"""
revision.py — single-shot guided revision prompts (spec §11).

"проведи ревизию холодильника" → the bot replies with a category checklist; the
user answers in one long message that flows through the normal parse→apply
pipeline. No FSM, no extra write path — this module only detects the trigger and
builds the prompt text.
"""
from __future__ import annotations

import re

FRIDGE = "fridge"
SHELVES = "shelves"
FREEZER = "freezer"

_TRIGGER = re.compile(r"ревизи", re.IGNORECASE)

_PROMPTS = {
    FRIDGE: (
        "Окей, идём по холодильнику. Ответь одним сообщением по разделам:\n"
        "- Готовая еда: что есть, что надо съесть сегодня, что выкинуть?\n"
        "- Молочка: молоко, йогурт, сыр, творог — что есть / мало / закончилось?\n"
        "- Белок: яйца, курица, мясо, рыба, готовый белок — что есть?\n"
        "- Овощи и фрукты: что есть, что под вопросом?\n"
        "- Хлеб / быстрая еда?\n"
        "- Соусы / приправы — чего не хватает?"
    ),
    SHELVES: (
        "Окей, идём по полкам. Ответь одним сообщением:\n"
        "- Кофе / чай?\n"
        "- Крупы / паста?\n"
        "- Консервы?\n"
        "- Соусы / масло?\n"
        "- Что закончилось или заканчивается?"
    ),
    FREEZER: (
        "Окей, проверяем морозилку. Ответь одним сообщением:\n"
        "- Замороженный белок (мясо, рыба, курица)?\n"
        "- Овощи / ягоды?\n"
        "- Готовая еда / заготовки?"
    ),
}


def detect_area(text: str) -> str | None:
    """Return the revision area if the message is a revision trigger, else None."""
    if not _TRIGGER.search(text or ""):
        return None
    low = text.lower()
    if "полк" in low or "полок" in low:
        return SHELVES
    if "морозил" in low:
        return FREEZER
    return FRIDGE  # default / "холодильник"


def revision_prompt(area: str) -> str:
    return _PROMPTS.get(area, _PROMPTS[FRIDGE])
