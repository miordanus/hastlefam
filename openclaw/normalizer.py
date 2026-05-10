from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from openclaw.client import SupabaseClient
from openclaw.parser import ParsedRow


def _today() -> date:
    return date.today()


@dataclass
class NormalizedRow:
    # ParsedRow fields (duplicated to avoid dataclass inheritance ordering issues)
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
    # Normalizer-added fields
    household_id: str
    source: str
    occurred_at: str
    dedup_fingerprint: str | None
    primary_tag: str | None
    is_duplicate: bool


def _compute_fingerprint(
    household_id: str,
    d: date,
    amount: Decimal,
    currency: str,
    merchant: str,
    direction: str,
) -> str:
    raw = f"{household_id}|{d}|{amount:.2f}|{currency}|{merchant.lower()}|{direction}|openclaw"
    return hashlib.sha256(raw.encode()).hexdigest()


def _fetch_known_tags(client: SupabaseClient) -> set[str]:
    rows = client.get(
        "transactions",
        params={
            "select": "primary_tag",
            "household_id": f"eq.{client.household_id}",
            "primary_tag": "not.is.null",
            "limit": "200",
        },
    )
    return {r["primary_tag"].lower() for r in rows if r.get("primary_tag")}


def normalize(rows: list[ParsedRow], client: SupabaseClient) -> list[NormalizedRow]:
    known_tags = _fetch_known_tags(client)
    today = _today()

    result: list[NormalizedRow] = []
    for row in rows:
        d = row.date if row.date is not None else today
        occurred_at = f"{d.isoformat()}T00:00:00+03:00"

        fingerprint: str | None = None
        if row.amount is not None:
            fingerprint = _compute_fingerprint(
                client.household_id, d, row.amount, row.currency,
                row.merchant_raw, row.direction,
            )

        merchant_lower = row.merchant_raw.lower()
        primary_tag = merchant_lower if merchant_lower in known_tags else None

        result.append(
            NormalizedRow(
                raw_line=row.raw_line,
                date=row.date,
                amount=row.amount,
                currency=row.currency,
                direction=row.direction,
                is_internal_transfer=row.is_internal_transfer,
                is_planned=row.is_planned,
                merchant_raw=row.merchant_raw,
                description_raw=row.description_raw,
                parse_status=row.parse_status,
                household_id=client.household_id,
                source="openclaw",
                occurred_at=occurred_at,
                dedup_fingerprint=fingerprint,
                primary_tag=primary_tag,
                is_duplicate=False,
            )
        )
    return result
