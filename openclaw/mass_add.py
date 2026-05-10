from __future__ import annotations

import argparse
import sys
from decimal import Decimal

from openclaw.client import SupabaseClient, SupabaseError
from openclaw.dedup import check as dedup_check
from openclaw.normalizer import NormalizedRow, normalize
from openclaw.parser import parse
from openclaw.preview import render_preview, render_summary


def _to_insert_dict(row: NormalizedRow) -> dict:
    d: dict = {
        "household_id": row.household_id,
        "direction": row.direction,
        "amount": float(row.amount) if row.amount is not None else None,
        "currency": row.currency,
        "occurred_at": row.occurred_at,
        "source": row.source,
        "parse_status": row.parse_status,
        "merchant_raw": row.merchant_raw,
        "description_raw": row.description_raw,
        "is_planned": row.is_planned,
        "is_internal_transfer": row.is_internal_transfer,
    }
    if row.dedup_fingerprint:
        d["dedup_fingerprint"] = row.dedup_fingerprint
    if row.primary_tag:
        d["primary_tag"] = row.primary_tag
    return d


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="OpenClaw mass-add: parse → preview → confirm → bulk insert to Supabase"
    )
    parser.add_argument("text", nargs="?", help="Transaction text (or omit to read from stdin)")
    parser.add_argument("--confirm", action="store_true", help="Skip interactive confirmation prompt")
    parser.add_argument("--json", dest="json_output", action="store_true", help="Output JSON instead of tables")
    parser.add_argument("--force-duplicates", action="store_true", help="Insert duplicate-fingerprint rows too")
    args = parser.parse_args(argv)

    raw = args.text if args.text else sys.stdin.read()
    if not raw.strip():
        print("Error: no input provided.", file=sys.stderr)
        return 1

    try:
        with SupabaseClient.from_env() as client:
            parsed_rows = parse(raw)
            normalized_rows = normalize(parsed_rows, client)
            deduped_rows = dedup_check(normalized_rows, client)

            render_preview(deduped_rows, force_duplicates=args.force_duplicates, json_output=args.json_output)

            if not args.confirm:
                answer = input("Proceed? [y/N] ").strip().lower()
                if answer not in ("y", "yes"):
                    print("Cancelled.")
                    return 0

            # amount is NOT NULL in the DB — rows with null amount cannot be inserted
            insertable = [
                r for r in deduped_rows
                if (not r.is_duplicate or args.force_duplicates) and r.amount is not None
            ]
            uninsertable_correction = [
                r for r in deduped_rows
                if r.amount is None and not r.is_duplicate
            ]

            skipped = sum(1 for r in deduped_rows if r.is_duplicate and not args.force_duplicates)

            if not insertable:
                render_summary(0, len(uninsertable_correction), skipped, [], json_output=args.json_output)
                return 0

            inserted = client.post("transactions", rows=[_to_insert_dict(r) for r in insertable])
            ids = [str(r.get("id", "")) for r in inserted]

            needs_correction_count = len(uninsertable_correction)

            render_summary(len(ids), needs_correction_count, skipped, ids, json_output=args.json_output)

    except SupabaseError as e:
        print(f"Supabase error {e.status_code}: {e.body}", file=sys.stderr)
        return 1
    except KeyError as e:
        print(f"Missing env var: {e}", file=sys.stderr)
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
