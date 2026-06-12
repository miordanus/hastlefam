"""
stub_parser.py — offline, rule-based stand-in for the LLM provider.

Plugs into LLMService exactly like OpenAIProvider (implements generate_json),
so the whole pipeline runs with no LLM creds. Naive on purpose: good enough to
demo inventory/list updates offline, not a real parser. Use the real provider
for anything beyond a smoke test.
"""
from __future__ import annotations

import re

# Split a message into clauses on commas / semicolons / sentence breaks.
_CLAUSE_SPLIT = re.compile(r"[,;.\n]+")

# Phrases stripped from a clause to leave (roughly) the product name.
_NOISE = [
    "в холодильнике", "в морозилке", "на полке", "на полках",
    "почти закончился", "почти закончилась", "почти закончилось", "почти закончились",
    "закончился", "закончилась", "закончилось", "закончились",
    "надо проверить", "под вопросом", "надо съесть", "осталось", "осталась", "остался",
    "выкинул", "выкинула", "выкинули", "выкинуть", "испортился", "испортилось",
    "почти полный", "почти полную", "полный", "добавь", "добавить", "в список",
    "мало", "есть", "штук", "штуки", "штука", "шт", "немного",
]


def _clean(text: str) -> str:
    t = text.strip().lower()
    for w in _NOISE:
        t = re.sub(rf"\b{re.escape(w)}\b", " ", t)
    t = re.sub(r"\d+", " ", t)
    return re.sub(r"\s+", " ", t).strip()


def _qty(clause: str):
    m = re.search(r"\b(\d+)\b", clause)
    return int(m.group(1)) if m else None


def _clause_to_action(clause: str):
    c = clause.strip().lower()
    if not c:
        return None

    if "выкин" in c or "испорт" in c:
        product = _clean(c)
        return {"intent": "discard", "product": product, "confidence": "low"} if product else None

    if "провер" in c or "под вопрос" in c:
        product = _clean(c)
        return {"intent": "mark_check_needed", "product": product, "status": "check", "confidence": "low"} if product else None

    if "добав" in c or "в список" in c:
        product = _clean(c)
        return {"intent": "add_to_shopping_list", "product": product, "reason": "manual_request", "confidence": "low"} if product else None

    if "почти" in c and "законч" in c:
        status = "almost_out"
    elif "законч" in c:
        status = "out"
    elif "мало" in c:
        status = "low"
    else:
        status = "in_stock"

    product = _clean(c)
    if not product:
        return None
    action = {"intent": "update_inventory", "product": product, "status": status, "confidence": "low"}
    q = _qty(c)
    if q is not None:
        action["quantity"] = q
        action["unit"] = "pcs"
    return action


def _split_products(action: dict) -> list[dict]:
    """An 'add курицу и сыр' clause yields two products."""
    parts = [p.strip() for p in re.split(r"\s+и\s+", action["product"]) if p.strip()]
    if len(parts) <= 1:
        return [action]
    return [{**action, "product": p} for p in parts]


class StubProvider:
    """LLM-shaped provider that parses with regex rules instead of a model."""

    async def generate_json(self, *, system_prompt: str, user_prompt: str, schema: dict) -> dict:
        actions: list[dict] = []
        for clause in _CLAUSE_SPLIT.split(user_prompt):
            action = _clause_to_action(clause)
            if action is None:
                continue
            if action["intent"] == "add_to_shopping_list":
                actions.extend(_split_products(action))
            else:
                actions.append(action)
        return {"actions": actions}
