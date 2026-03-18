from typing import Any, Awaitable, Callable, Dict
import logging

from aiogram import BaseMiddleware
from aiogram.types import Message, TelegramObject

log = logging.getLogger(__name__)


class LoggingMiddleware(BaseMiddleware):
    async def __call__(
        self,
        handler: Callable[[TelegramObject, Dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: Dict[str, Any],
    ) -> Any:
        if isinstance(event, Message):
            user_id = event.from_user.id if event.from_user else "?"
            text_preview = (event.text or "")[:80].replace("\n", " ")
            log.info(
                "msg from=%s chat=%s text=%r",
                user_id,
                event.chat.id if event.chat else "?",
                text_preview,
            )
        else:
            log.debug("update type=%s", type(event).__name__)
        return await handler(event, data)
