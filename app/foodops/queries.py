"""
queries.py — deterministic detection of read-only "что купить?" questions.

These are answered straight from the shopping list (no LLM), so they never hit
the parser. Kept tiny and keyword-based for MVP (spec §12 useful queries).
"""
from __future__ import annotations

import re

_BUY_PATTERNS = [
    r"что\s+(?:сейчас\s+|срочно\s+)?(?:надо\s+)?купить",
    r"что\s+покупать",
    r"купить\s+сегодня",
    r"список\s+покупок",
    r"что\s+в\s+списке",
    r"шоппинг[\s-]*лист",
]
_BUY_RE = re.compile("|".join(_BUY_PATTERNS), re.IGNORECASE)

_SPOILAGE_PATTERNS = [
    r"что\s+скоро\s+испорт",
    r"что\s+(?:может\s+)?испорт",
    r"что\s+портит",
    r"риск\s+порчи",
    r"что\s+пропадает",
]
_SPOILAGE_RE = re.compile("|".join(_SPOILAGE_PATTERNS), re.IGNORECASE)

_WASTE_PATTERNS = [
    r"что\s+выкин",
    r"сколько\s+выкин",
    r"что\s+проёбыва",
    r"что\s+проебыва",
    r"что\s+пропадает\s+зря",
    r"отчёт\s+по\s+отход",
    r"отчет\s+по\s+отход",
    r"что\s+чаще\s+всего\s+выкид",
]
_WASTE_RE = re.compile("|".join(_WASTE_PATTERNS), re.IGNORECASE)


def is_what_to_buy(text: str) -> bool:
    return bool(_BUY_RE.search(text or ""))


def is_spoilage(text: str) -> bool:
    return bool(_SPOILAGE_RE.search(text or ""))


def is_waste(text: str) -> bool:
    return bool(_WASTE_RE.search(text or ""))
