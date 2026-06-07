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


def is_what_to_buy(text: str) -> bool:
    return bool(_BUY_RE.search(text or ""))
