"""
expense_parser.py — deterministic free-text parser for HastleFam.

Pure module: no Telegram, no DB, no side effects.
Input: raw user text string.
Output: ParseResult dataclass.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date, timedelta, timezone
from decimal import Decimal, InvalidOperation
from typing import Optional

from app.domain.enums import Currency, TransactionDirection


# ─── Currency tokens ─────────────────────────────────────────────────────────

_CURRENCY_MAP: dict[str, Currency] = {
    "rub": Currency.RUB,
    "руб": Currency.RUB,
    "₽": Currency.RUB,
    "usd": Currency.USD,
    "$": Currency.USD,
    "usdt": Currency.USDT,
    "eur": Currency.EUR,
    "€": Currency.EUR,
}

_CURRENCY_TOKENS = set(_CURRENCY_MAP.keys())

# ─── Patterns ─────────────────────────────────────────────────────────────────

# Exchange: "250 usdt -> 230 eur" or "250 usdt → 230 eur" or "250 usdt to 230 eur"
_EXCHANGE_RE = re.compile(
    r"^\s*(\d+(?:[\.,]\d{1,2})?)\s+(\S+)\s*(?:->|→|to|в)\s*(\d+(?:[\.,]\d{1,2})?)\s+(\S+)\s*$",
    re.IGNORECASE,
)

# Tags: #word
_TAG_RE = re.compile(r"#(\w+)", re.IGNORECASE)

# Date hints
_DATE_HINTS: dict[str, int] = {
    "вчера": -1,
    "yesterday": -1,
    "сегодня": 0,
    "today": 0,
    "tomorrow": 1,
    "завтра": 1,
}

# ISO date pattern: YYYY-MM-DD
_ISO_DATE_RE = re.compile(r"\b(\d{4}-\d{2}-\d{2})\b")

# Short date patterns: DD-MM, DD.MM, D-M, D.M (day-month, current year assumed)
_SHORT_DATE_RE = re.compile(r"\b(\d{1,2})[.\-/](\d{1,2})\b")

# Amount: leading number (with comma or dot decimal)
_AMOUNT_RE = re.compile(r"^[+]?(\d+(?:[\.,]\d{1,2})?)")

# Income prefix: starts with +
_INCOME_RE = re.compile(r"^\+")


# ─── Result ────────────────────────────────────────────────────────────────────

@dataclass
class ParseResult:
    """Structured result from free-text parsing. None fields = not parsed."""
    direction: TransactionDirection
    amount: Optional[Decimal]
    currency: Currency
    currency_explicit: bool  # True if currency was explicitly stated by user
    merchant: Optional[str]
    primary_tag: Optional[str]
    extra_tags: list[str]
    occurred_date: date
    date_explicit: bool  # True if date was explicitly stated by user
    is_exchange: bool = False
    # exchange-specific fields
    from_amount: Optional[Decimal] = None
    from_currency: Optional[Currency] = None
    to_amount: Optional[Decimal] = None
    to_currency: Optional[Currency] = None
    # parse quality
    ok: bool = True
    error: Optional[str] = None

    @property
    def has_tag(self) -> bool:
        return self.primary_tag is not None


def parse(text: str) -> ParseResult:
    """
    Parse free-text user input into a ParseResult.
    Deterministic. No LLM. No external calls.
    """
    text = text.strip()
    today = _today()

    # ── Exchange pattern ────────────────────────────────────────────────────
    m = _EXCHANGE_RE.match(text)
    if m:
        from_amount_raw, from_cur_raw, to_amount_raw, to_cur_raw = m.groups()
        from_cur = _resolve_currency(from_cur_raw)
        to_cur = _resolve_currency(to_cur_raw)
        if from_cur and to_cur:
            from_amt = _parse_amount(from_amount_raw)
            to_amt = _parse_amount(to_amount_raw)
            if from_amt and to_amt:
                return ParseResult(
                    direction=TransactionDirection.EXPENSE,  # will be overridden to EXCHANGE
                    amount=from_amt,
                    currency=from_cur,
                    currency_explicit=True,
                    merchant=None,
                    primary_tag=None,
                    extra_tags=[],
                    occurred_date=today,
                    date_explicit=False,
                    is_exchange=True,
                    from_amount=from_amt,
                    from_currency=from_cur,
                    to_amount=to_amt,
                    to_currency=to_cur,
                )

    # ── Direction: income if starts with + ──────────────────────────────────
    direction = TransactionDirection.INCOME if text.startswith("+") else TransactionDirection.EXPENSE
    working = text.lstrip("+").strip()

    # ── Extract tags ────────────────────────────────────────────────────────
    tags = _TAG_RE.findall(working)
    working_no_tags = _TAG_RE.sub("", working).strip()
    primary_tag = tags[0].lower() if tags else None
    extra_tags = [t.lower() for t in tags[1:]]

    # ── Extract date hint ───────────────────────────────────────────────────
    occurred_date, date_explicit, working_no_tags = _extract_date(working_no_tags, today)

    # ── Tokenize remaining text ─────────────────────────────────────────────
    tokens = working_no_tags.split()

    if not tokens:
        return _error_result("Не вижу сумму. Начни сообщение с числа.")

    # First token should be amount
    amount = _parse_amount(tokens[0])
    if amount is None:
        return _error_result("Не вижу сумму. Начни сообщение с числа.")

    remaining = tokens[1:]

    # ── Detect currency in remaining tokens ─────────────────────────────────
    currency = Currency.RUB
    currency_explicit = False
    filtered_remaining: list[str] = []

    for token in remaining:
        resolved = _resolve_currency(token)
        if resolved and not currency_explicit:
            currency = resolved
            currency_explicit = True
        else:
            filtered_remaining.append(token)

    merchant_str = " ".join(filtered_remaining).strip() or None

    if merchant_str and len(merchant_str) < 2:
        return _error_result("Не вижу, что это за трата. Добавь короткое название после суммы.")

    return ParseResult(
        direction=direction,
        amount=amount,
        currency=currency,
        currency_explicit=currency_explicit,
        merchant=merchant_str,
        primary_tag=primary_tag,
        extra_tags=extra_tags,
        occurred_date=occurred_date,
        date_explicit=date_explicit,
    )


# ─── Helpers ──────────────────────────────────────────────────────────────────

def _today() -> date:
    from datetime import datetime
    return datetime.now(timezone.utc).date()


def _parse_amount(raw: str) -> Optional[Decimal]:
    try:
        return Decimal(raw.replace(",", "."))
    except InvalidOperation:
        return None


def _resolve_currency(token: str) -> Optional[Currency]:
    return _CURRENCY_MAP.get(token.lower())


def _extract_date(text: str, today: date) -> tuple[date, bool, str]:
    """Extract date hint from text; return (date, was_explicit, cleaned_text)."""
    lower = text.lower()

    # Check word hints
    for hint, delta in _DATE_HINTS.items():
        if hint in lower:
            result_date = today + timedelta(days=delta)
            cleaned = re.sub(re.escape(hint), "", text, flags=re.IGNORECASE).strip()
            return result_date, True, cleaned

    # Check ISO date (YYYY-MM-DD)
    m = _ISO_DATE_RE.search(text)
    if m:
        try:
            result_date = date.fromisoformat(m.group(1))
            cleaned = _ISO_DATE_RE.sub("", text).strip()
            return result_date, True, cleaned
        except ValueError:
            pass

    # Check short date (DD-MM, DD.MM, D-M, D.M — day first, current year)
    m = _SHORT_DATE_RE.search(text)
    if m:
        try:
            day = int(m.group(1))
            month = int(m.group(2))
            result_date = date(today.year, month, day)
            cleaned = _SHORT_DATE_RE.sub("", text, count=1).strip()
            return result_date, True, cleaned
        except ValueError:
            pass

    return today, False, text


def _error_result(error: str) -> ParseResult:
    return ParseResult(
        direction=TransactionDirection.EXPENSE,
        amount=None,
        currency=Currency.RUB,
        currency_explicit=False,
        merchant=None,
        primary_tag=None,
        extra_tags=[],
        occurred_date=_today(),
        date_explicit=False,
        ok=False,
        error=error,
    )
