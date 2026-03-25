"""debt_parser.py — Pure deterministic regex parser for debt messages.

Patterns:
  дал 500 Васе          → THEY_OWE (тебе должны), amount=500, counterparty=Вася, currency=RUB
  дал 50 USD Марине     → THEY_OWE, currency=USD
  взял 1000 у Пети      → I_OWE (ты должен), amount=1000, counterparty=Петя
  взял 200 EUR у Маши   → I_OWE, currency=EUR

Returns DebtParseResult | None. If text does not match — returns None.
No I/O, no side effects.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation

from app.domain.enums import DebtDirection

# Currency keywords (case-insensitive)
_CURRENCY_MAP = {
    "rub": "RUB", "руб": "RUB", "₽": "RUB",
    "usd": "USD", "$": "USD", "долларов": "USD", "доллар": "USD",
    "eur": "EUR", "€": "EUR", "евро": "EUR",
    "pln": "PLN", "zł": "PLN", "злот": "PLN",
    "usdt": "USDT",
}

# дал/дала <amount> [currency] <name>
_GAVE_PATTERN = re.compile(
    r"^дал[аи]?\s+"            # дал / дала / дали
    r"([\d.,]+)\s*"            # amount
    r"([a-zA-Zа-яёА-ЯЁ₽€$]+\s*)?"  # optional currency
    r"([А-ЯЁа-яёA-Za-z][а-яёa-z]+)$",  # counterparty (capitalized word)
    re.IGNORECASE | re.UNICODE,
)

# взял/взяла <amount> [currency] у <name>
_TOOK_PATTERN = re.compile(
    r"^взял[аи]?\s+"           # взял / взяла / взяли
    r"([\d.,]+)\s*"            # amount
    r"([a-zA-Zа-яёА-ЯЁ₽€$]+\s*)?"  # optional currency
    r"у\s+"                    # "у"
    r"([А-ЯЁа-яёA-Za-z][а-яёa-z]+)$",  # counterparty
    re.IGNORECASE | re.UNICODE,
)


@dataclass
class DebtParseResult:
    direction: DebtDirection
    amount: Decimal
    currency: str
    counterparty: str


def _parse_amount(raw: str) -> Decimal | None:
    try:
        return Decimal(raw.replace(",", "."))
    except InvalidOperation:
        return None


def _parse_currency(raw: str | None) -> str:
    if not raw:
        return "RUB"
    key = raw.strip().lower().rstrip()
    return _CURRENCY_MAP.get(key, "RUB")


def parse(text: str) -> DebtParseResult | None:
    """Parse text into DebtParseResult or return None if not a debt message."""
    text = text.strip()

    # Try "дал" pattern (they owe you)
    m = _GAVE_PATTERN.match(text)
    if m:
        amount = _parse_amount(m.group(1))
        if amount and amount > 0:
            currency = _parse_currency(m.group(2))
            counterparty = m.group(3).strip().capitalize()
            return DebtParseResult(
                direction=DebtDirection.THEY_OWE,
                amount=amount,
                currency=currency,
                counterparty=counterparty,
            )

    # Try "взял" pattern (you owe them)
    m = _TOOK_PATTERN.match(text)
    if m:
        amount = _parse_amount(m.group(1))
        if amount and amount > 0:
            currency = _parse_currency(m.group(2))
            counterparty = m.group(3).strip().capitalize()
            return DebtParseResult(
                direction=DebtDirection.I_OWE,
                amount=amount,
                currency=currency,
                counterparty=counterparty,
            )

    return None
