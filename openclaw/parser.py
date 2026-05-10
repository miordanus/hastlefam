from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal, InvalidOperation

INCOME_KEYWORDS: frozenset[str] = frozenset(
    {"зп", "зарплата", "доход", "refund", "salary", "income", "cashback"}
)
TRANSFER_KEYWORDS: frozenset[str] = frozenset({"перевод", "transfer"})
EXCHANGE_KEYWORDS: frozenset[str] = frozenset({"exchange", "обмен"})
CURRENCY_TOKENS: frozenset[str] = frozenset({"USD", "EUR", "AMD", "USDT"})

# DD.MM, DD-MM, DD/MM — but only when NOT preceded/followed by another digit
# (avoids matching YYYY-MM-DD fragments)
_DATE_SHORT = re.compile(r'(?<!\d)(\d{1,2})[.\-/](\d{1,2})(?!\d)')
_DATE_LONG = re.compile(r'(\d{4})-(\d{2})-(\d{2})')
_AMOUNT_PLUS = re.compile(r'\+(\d+(?:[.,]\d+)?)')
_AMOUNT_BARE = re.compile(r'(?<!\d)(\d+(?:[.,]\d+)?)(?!\d)')


@dataclass
class ParsedRow:
    raw_line: str
    date: date | None
    amount: Decimal | None
    currency: str
    direction: str
    is_internal_transfer: bool
    is_planned: bool
    merchant_raw: str
    description_raw: str
    parse_status: str


def _extract_date(text: str, today: date) -> tuple[date | None, str]:
    """Return (parsed_date, text_with_date_removed). Long form first to avoid partial match."""
    m = _DATE_LONG.search(text)
    if m:
        try:
            d = date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
            return d, (text[: m.start()] + text[m.end() :]).strip()
        except ValueError:
            pass

    m = _DATE_SHORT.search(text)
    if m:
        try:
            d = date(today.year, int(m.group(2)), int(m.group(1)))
            return d, (text[: m.start()] + text[m.end() :]).strip()
        except ValueError:
            pass

    lower = text.lower()
    if "позавчера" in lower:
        return today - timedelta(days=2), re.sub("позавчера", "", text, flags=re.IGNORECASE).strip()
    if "вчера" in lower:
        return today - timedelta(days=1), re.sub("вчера", "", text, flags=re.IGNORECASE).strip()

    return None, text


def _parse_line(line: str, today: date) -> ParsedRow:
    remaining = line.strip()
    is_planned = False

    # [planned] flag — strip before anything else
    if re.search(r"\[planned\]", remaining, re.IGNORECASE):
        is_planned = True
        remaining = re.sub(r"\[planned\]", "", remaining, flags=re.IGNORECASE).strip()

    # Date
    parsed_date, remaining = _extract_date(remaining, today)
    if parsed_date is None:
        parsed_date = today

    # Future date + plan keyword
    lower = remaining.lower()
    if parsed_date > today and ("план" in lower or "plan" in lower):
        is_planned = True

    # Currency — remove token before amount extraction to avoid confusion
    currency = "RUB"
    for token in CURRENCY_TOKENS:
        if re.search(r"(?i)\b" + token + r"\b", remaining):
            currency = token.upper()
            remaining = re.sub(r"(?i)\b" + token + r"\b", "", remaining).strip()
            break

    # Amount — prefer +N form (income signal) over bare N
    amount: Decimal | None = None
    has_plus = False
    m = _AMOUNT_PLUS.search(remaining)
    if m:
        has_plus = True
        try:
            amount = Decimal(m.group(1).replace(",", "."))
        except InvalidOperation:
            pass
        remaining = (remaining[: m.start()] + remaining[m.end() :]).strip()
    else:
        m = _AMOUNT_BARE.search(remaining)
        if m:
            try:
                amount = Decimal(m.group(1).replace(",", "."))
            except InvalidOperation:
                pass
            remaining = (remaining[: m.start()] + remaining[m.end() :]).strip()

    # Direction — check keywords against what's left after amount extraction
    words = set(re.split(r"\W+", remaining.lower()))
    is_internal_transfer = False
    if has_plus or bool(words & INCOME_KEYWORDS):
        direction = "income"
        for kw in INCOME_KEYWORDS:
            remaining = re.sub(r"(?i)\b" + kw + r"\b", "", remaining).strip()
    elif bool(words & EXCHANGE_KEYWORDS):
        direction = "exchange"
        for kw in EXCHANGE_KEYWORDS:
            remaining = re.sub(r"(?i)\b" + kw + r"\b", "", remaining).strip()
    elif bool(words & TRANSFER_KEYWORDS):
        direction = "expense"
        is_internal_transfer = True
        for kw in TRANSFER_KEYWORDS:
            remaining = re.sub(r"(?i)\b" + kw + r"\b", "", remaining).strip()
    else:
        direction = "expense"

    merchant = re.sub(r"\s+", " ", remaining).strip(" ,;-")
    parse_status = "ok" if amount is not None else "needs_correction"

    return ParsedRow(
        raw_line=line,
        date=parsed_date,
        amount=amount,
        currency=currency,
        direction=direction,
        is_internal_transfer=is_internal_transfer,
        is_planned=is_planned,
        merchant_raw=merchant,
        description_raw=merchant,
        parse_status=parse_status,
    )


def parse(raw: str, today: date | None = None) -> list[ParsedRow]:
    """Parse a raw multiline / slash-separated transaction dump into ParsedRows."""
    if today is None:
        today = date.today()
    # Split on newlines OR " / " (space-slash-space) to avoid splitting DD/MM dates
    lines = re.split(r"\n| / ", raw)
    return [_parse_line(line, today) for line in lines if line.strip()]
