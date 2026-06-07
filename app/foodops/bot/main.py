"""
FoodOps bot worker — second aiogram poller in the hastlefam repo.

Separate BotFather token from the finance bot, so food messages never collide
with finance free-text capture. Shares the repo, DB, LLM client, and deploy.
Mirrors app/bot/main.py's Redis single-poller lock + conflict-exit pattern with
its own lock key.
"""
import asyncio
import logging
import os

from aiogram import Bot, Dispatcher
from aiogram.client.session.aiohttp import AiohttpSession
from aiogram.exceptions import TelegramConflictError
from aiogram.types import ErrorEvent

from app.foodops.bot.handlers.start import router as start_router
from app.foodops.bot.handlers.capture import router as capture_router
from app.bot.middlewares.logging import LoggingMiddleware
from app.infrastructure.config.settings import get_settings
from app.infrastructure.logging.logger import configure_logging

log = logging.getLogger(__name__)

_POLLER_LOCK_KEY = "hastlefam:foodbot:poller"
_POLLER_LOCK_TTL = 60  # seconds
_LOCK_RENEW_INTERVAL = 20  # seconds

_global_lock = None
_global_redis = None


async def _release_global_lock():
    global _global_lock, _global_redis
    try:
        if _global_lock:
            await _global_lock.release()
    except Exception:
        pass
    try:
        if _global_redis and _global_redis != "exit":
            await _global_redis.aclose()
    except Exception:
        pass


class _ConflictExitSession(AiohttpSession):
    """Exit immediately on TelegramConflictError so the platform restarts us
    cleanly after a rolling deploy (same pattern as the finance bot)."""

    async def make_request(self, bot, method, **kwargs):
        try:
            return await super().make_request(bot, method, **kwargs)
        except TelegramConflictError:
            log.error("TelegramConflictError (foodbot): another instance is polling. Exiting.")
            await _release_global_lock()
            os._exit(1)


async def _renew_lock(lock) -> None:
    while True:
        await asyncio.sleep(_LOCK_RENEW_INTERVAL)
        try:
            await lock.extend(_POLLER_LOCK_TTL)
        except Exception as exc:
            log.warning("foodbot poller lock extend failed: %s", exc)
            break


async def _setup_redis(redis_url: str):
    try:
        import redis.asyncio as aioredis
    except ImportError:
        log.warning("redis not installed — foodbot poller lock disabled")
        return None, None
    try:
        client = aioredis.from_url(redis_url, decode_responses=True)
        await client.ping()
        lock = client.lock(_POLLER_LOCK_KEY, timeout=_POLLER_LOCK_TTL)
        acquired = await lock.acquire(blocking=True, blocking_timeout=70)
        if not acquired:
            log.warning("foodbot poller lock held by another instance — exiting")
            await client.aclose()
            return "exit", None
        log.info("foodbot poller lock acquired")
        return client, lock
    except Exception as exc:
        log.warning("Redis unavailable (%s) — foodbot poller lock disabled", exc)
        return None, None


async def main() -> None:
    settings = get_settings()
    configure_logging(settings.log_level)
    logging.getLogger("apscheduler").setLevel(logging.WARNING)

    if not settings.foodops_telegram_bot_token:
        log.error(
            "FOODOPS_TELEGRAM_BOT_TOKEN is not set — foodbot worker cannot start. "
            "This process belongs to the FoodOps Worker service only."
        )
        return

    redis_client, lock = await _setup_redis(settings.redis_url)
    if redis_client == "exit":
        return

    global _global_lock, _global_redis
    _global_lock = lock
    _global_redis = redis_client

    bot = Bot(token=settings.foodops_telegram_bot_token, session=_ConflictExitSession())
    dp = Dispatcher()

    dp.message.middleware(LoggingMiddleware())
    if redis_client is not None:
        from app.bot.middlewares.idempotency import IdempotencyMiddleware
        dp.message.middleware(IdempotencyMiddleware(redis_client))

    # start/help first (specific), catch-all capture last
    dp.include_router(start_router)
    dp.include_router(capture_router)

    @dp.errors()
    async def _error_handler(event: ErrorEvent) -> bool:
        log.error(
            "unhandled exception in foodbot handler update_id=%s",
            getattr(event.update, "update_id", "?"),
            exc_info=event.exception,
        )
        return True

    log.info("foodbot routers registered: %d", len(dp.sub_routers))
    log.info("foodbot starting polling")

    renew_task = asyncio.create_task(_renew_lock(lock)) if lock else None
    try:
        await dp.start_polling(bot, drop_pending_updates=False)
    except Exception as exc:
        log.error("foodbot polling failed: %s", exc, exc_info=True)
        raise
    finally:
        if renew_task:
            renew_task.cancel()
        if lock:
            try:
                await lock.release()
            except Exception:
                pass
        if redis_client and redis_client != "exit":
            await redis_client.aclose()


if __name__ == "__main__":
    asyncio.run(main())
