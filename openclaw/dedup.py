from __future__ import annotations

import dataclasses

from openclaw.client import SupabaseClient
from openclaw.normalizer import NormalizedRow


def check(rows: list[NormalizedRow], client: SupabaseClient) -> list[NormalizedRow]:
    """Check each row's dedup_fingerprint against the DB. Returns rows with is_duplicate set."""
    result: list[NormalizedRow] = []
    for row in rows:
        if row.dedup_fingerprint is None:
            result.append(row)
            continue
        existing = client.get(
            "transactions",
            params={
                "dedup_fingerprint": f"eq.{row.dedup_fingerprint}",
                "select": "id",
                "limit": "1",
            },
        )
        if existing:
            row = dataclasses.replace(row, is_duplicate=True)
        result.append(row)
    return result
