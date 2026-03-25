"""split_parser.py — Pure deterministic parser for split (date-range) transactions.

Pattern:  700 еда 13.03-19.03  or  700 еда 13.03–19.03
Parses:   amount, merchant/tag, date_from (DD.MM), date_to (DD.MM)

Validation:
  - date_to >= date_from
  - range <= 31 days

Returns SplitParseResult | None. No I/O, no side effects.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal, InvalidOperation


@dataclass
class SplitParseResult:
    amount: Decimal         # amount per day (split evenly)
    merchant: str           # tag / merchant
    date_from: date
    date_to: date
    n_days: int             # inclusive count of days
    amount_per_day: Decimal


# Pattern: <amount> <merchant> <DD.MM>[-–]<DD.MM>
# Supports both hyphen and en-dash as range separator
_SPLIT_PATTERN = re.compile(
    r"^([\d.,]+)\s+"                                     # amount
    r"([^\d]+?)\s+"                                      # merchant (non-digit chars)
    r"(\d{1,2})[./\-](\d{1,2})"                         # date_from DD.MM or DD-MM or DD/MM
    r"\s*[–\-]\s*"                                       # range separator (– or -)
    r"(\d{1,2})[./\-](\d{1,2})$",                       # date_to
    re.UNICODE,
)


def _resolve_date(day: int, month: int) -> date:
    """Resolve DD.MM to a full date using current year; roll to next year if in past."""
    today = date.today()
    try:
        d = date(today.year, month, day)
    except ValueError:
        raise ValueError(f"Invalid date {day}.{month:02d}")
    return d


def parse(text: str) -> SplitParseResult | None:
    """Parse split transaction text or return None."""
    text = text.strip()
    m = _SPLIT_PATTERN.match(text)
    if not m:
        return None

    raw_amount, merchant, fd, fm, td, tm = (
        m.group(1), m.group(2).strip(),
        int(m.group(3)), int(m.group(4)),
        int(m.group(5)), int(m.group(6)),
    )

    try:
        amount = Decimal(raw_amount.replace(",", "."))
        if amount <= 0:
            return None
    except InvalidOperation:
        return None

    if not merchant:
        return None

    try:
        date_from = _resolve_date(fd, fm)
        date_to = _resolve_date(td, tm)
    except ValueError:
        return None

    # If date_to < date_from, try rolling date_to to next year
    if date_to < date_from:
        try:
            date_to = date(date_to.year + 1, date_to.month, date_to.day)
        except ValueError:
            return None

    if date_to < date_from:
        return None

    n_days = (date_to - date_from).days + 1  # inclusive
    if n_days > 31:
        return None  # range too wide

    amount_per_day = (amount / n_days).quantize(Decimal("0.01"))

    return SplitParseResult(
        amount=amount,
        merchant=merchant,
        date_from=date_from,
        date_to=date_to,
        n_days=n_days,
        amount_per_day=amount_per_day,
    )
