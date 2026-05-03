"""Redis-backed temporary storage for duplicate-suspect transaction drafts.

Keyed by a short UUID so callback_data stays well under Telegram's 64-byte limit.
Falls back to None (silent drop) when Redis is unavailable.
"""
from __future__ import annotations

import json
import uuid
from typing import Any

_client = None
_TTL = 300  # 5 minutes — enough to tap the inline button


def set_client(client) -> None:
    global _client
    _client = client


async def store(draft: dict[str, Any]) -> str | None:
    """Store draft dict in Redis, return a short UUID key or None if unavailable."""
    if _client is None:
        return None
    key = str(uuid.uuid4())
    try:
        await _client.set(f"dup:{key}", json.dumps(draft, default=str), ex=_TTL)
        return key
    except Exception:
        return None


async def retrieve(key: str) -> dict[str, Any] | None:
    """Retrieve-and-delete draft from Redis. Returns None if expired or unavailable."""
    if _client is None:
        return None
    try:
        raw = await _client.getdel(f"dup:{key}")
        return json.loads(raw) if raw else None
    except Exception:
        return None
