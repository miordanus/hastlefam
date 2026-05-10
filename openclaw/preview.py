from __future__ import annotations

import json
from decimal import Decimal

from openclaw.normalizer import NormalizedRow

_SEP = "─" * 72


def _status_symbol(row: NormalizedRow) -> str:
    if row.is_duplicate:
        return "duplicate ⟳"
    if row.parse_status == "needs_correction":
        return "⚠ needs_correction"
    return "✓"


def _net_by_currency(rows: list[NormalizedRow]) -> dict[str, Decimal]:
    totals: dict[str, Decimal] = {}
    for row in rows:
        if row.is_duplicate or row.amount is None:
            continue
        sign = Decimal("-1") if row.direction == "expense" else Decimal("1")
        if row.direction == "exchange":
            continue
        totals[row.currency] = totals.get(row.currency, Decimal("0")) + sign * row.amount
    return totals


def render_preview(
    rows: list[NormalizedRow],
    force_duplicates: bool = False,
    json_output: bool = False,
) -> None:
    n_dup = sum(1 for r in rows if r.is_duplicate)
    n_corr = sum(1 for r in rows if r.parse_status == "needs_correction" and not r.is_duplicate)
    n_new = sum(1 for r in rows if not r.is_duplicate and r.parse_status != "needs_correction")

    if json_output:
        data = {
            "summary": {"new": n_new, "duplicate": n_dup, "needs_correction": n_corr},
            "rows": [
                {
                    "index": i + 1,
                    "date": str(r.date) if r.date else None,
                    "direction": r.direction,
                    "amount": float(r.amount) if r.amount is not None else None,
                    "currency": r.currency,
                    "merchant": r.merchant_raw,
                    "tag": r.primary_tag,
                    "status": "duplicate" if r.is_duplicate else r.parse_status,
                }
                for i, r in enumerate(rows)
            ],
        }
        print(json.dumps(data, ensure_ascii=False))
        return

    print("OpenClaw — mass add preview")
    print(f"{n_new} new  |  {n_dup} duplicate  |  {n_corr} needs_correction")
    print(_SEP)
    print(f"  {'#':>3}  {'date':<12} {'dir':<8} {'amount':>10}  {'cur':<5} {'merchant':<20} {'tag':<12} status")

    for i, row in enumerate(rows):
        amt = f"{row.amount:>10.2f}" if row.amount is not None else f"{'???':>10}"
        date_str = str(row.date) if row.date else "???"
        tag_str = (row.primary_tag or "")[:12]
        merchant_str = row.merchant_raw[:20]
        status = _status_symbol(row)
        print(f"  {i + 1:>3}  {date_str:<12} {row.direction:<8} {amt}  {row.currency:<5} {merchant_str:<20} {tag_str:<12} {status}")

    print(_SEP)

    # Net — only if no needs_correction rows with unknown amount in the new set
    new_rows = [r for r in rows if not r.is_duplicate]
    has_unknown_amount = any(r.amount is None for r in new_rows)
    if not has_unknown_amount:
        net = _net_by_currency(rows)
        for cur, total in net.items():
            sign = "+" if total >= 0 else ""
            print(f"Net new ({cur}): {sign}{total:,.2f}")


def render_summary(
    inserted_count: int,
    needs_correction_count: int,
    skipped_duplicates: int,
    ids: list[str],
    json_output: bool = False,
) -> None:
    if json_output:
        print(json.dumps({
            "inserted_count": inserted_count,
            "needs_correction_count": needs_correction_count,
            "skipped_duplicates_count": skipped_duplicates,
            "ids": ids,
        }))
        return
    print(f"Inserted {inserted_count} | Needs correction: {needs_correction_count} | Skipped duplicates: {skipped_duplicates}")
    if ids:
        print(f"IDs: {ids}")
