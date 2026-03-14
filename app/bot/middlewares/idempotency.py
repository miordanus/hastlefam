"""
idempotency.py — delivery-level dedup middleware.

Prevents the same Telegram message from being processed twice
(e.g. after a crash-and-restart where Telegram retries the delivery).

Key: msg_idem:{chat_id}:{message_id}  TTL: 300s
If key already exists, the update is silently dropped — no handler runs,
no reply is sent.

This is NOT business-level duplicate detection. It only guards against
duplicate Telegram deliveries of the exact same update.
"""
from __future__ import annotations

import logging
from typing import Any, Awaitable, Callable

from aiogram import BaseMiddleware
from aiogram.types import Message

log = logging.getLogger(__name__)

_TTL = 300  # 5 minutes


class IdempotencyMiddleware(BaseMiddleware):
    def __init__(self, redis) -> None:
        self._redis = redis

    async def __call__(
        self,
        handler: Callable[[Message, dict[str, Any]], Awaitable[Any]],
        event: Message,
        data: dict[str, Any],
    ) -> Any:
        chat_id = event.chat.id if event.chat else None
        msg_id = event.message_id

        if chat_id is not None and msg_id is not None:
            key = f"msg_idem:{chat_id}:{msg_id}"
            try:
                set_result = await self._redis.set(key, "1", nx=True, ex=_TTL)
                if set_result is None:
                    # Key already existed — already processed this delivery
                    log.debug("idempotency: duplicate delivery dropped chat=%s msg=%s", chat_id, msg_id)
                    return
            except Exception as exc:
                # Redis failure must not block message processing
                log.warning("idempotency: redis error, proceeding without check: %s", exc)

        return await handler(event, data)
