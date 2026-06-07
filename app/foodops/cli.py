"""
cli.py — local REPL for FoodOps, no Telegram required.

Reads lines from stdin, runs each through the real orchestration core
(handle.handle_message) against the configured database, and prints the reply.

  python -m app.foodops.cli            # real LLM (needs OPENAI_BASE_URL/KEY)
  python -m app.foodops.cli --stub     # offline rule-based parser, no creds

Resolves the household/user from the DB (first household; --user picks a
telegram_id). Run app.seeds.run_all first to have a household + baseline products.
"""
from __future__ import annotations

import argparse
import asyncio
import sys

from sqlalchemy import text

from app.application.services.llm_service import LLMService
from app.foodops import handle
from app.foodops.parsers.stub_parser import StubProvider
from app.infrastructure.db.base import DB_SCHEMA
from app.infrastructure.db.session import SessionLocal


def _resolve_ids(db, telegram_id: str | None):
    household_id = db.execute(
        text(f"SELECT id FROM {DB_SCHEMA}.households ORDER BY created_at LIMIT 1")
    ).scalar()
    if household_id is None:
        raise SystemExit("No household found. Run: python -m app.seeds.run_all")
    if telegram_id:
        user_id = db.execute(
            text(f"SELECT id FROM {DB_SCHEMA}.users WHERE telegram_id = :t LIMIT 1"),
            {"t": telegram_id},
        ).scalar()
    else:
        user_id = db.execute(
            text(f"SELECT id FROM {DB_SCHEMA}.users WHERE household_id = :h ORDER BY created_at LIMIT 1"),
            {"h": household_id},
        ).scalar()
    return household_id, user_id


async def _run(stub: bool, telegram_id: str | None) -> None:
    service = LLMService(StubProvider()) if stub else None
    mode = "stub (offline)" if stub else "LLM"
    print(f"FoodOps CLI [{mode}] — type a message, Ctrl-D to quit.\n")
    for line in sys.stdin:
        text_in = line.strip()
        if not text_in:
            continue
        with SessionLocal() as db:
            household_id, user_id = _resolve_ids(db, telegram_id)
            reply = await handle.handle_message(db, household_id, user_id, text_in, parse_service=service)
            db.commit()
        print(reply)
        print("-" * 40)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--stub", action="store_true", help="use the offline rule-based parser")
    ap.add_argument("--user", default=None, help="telegram_id of the acting user")
    args = ap.parse_args()
    asyncio.run(_run(args.stub, args.user))


if __name__ == "__main__":
    main()
