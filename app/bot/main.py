import asyncio
import logging
import os

from aiogram import Bot, Dispatcher
from aiogram.client.session.aiohttp import AiohttpSession
from aiogram.exceptions import TelegramConflictError
from aiogram.types import ErrorEvent
from app.bot.handlers.cancel import router as cancel_router
from app.bot.handlers.start import router as start_router
from app.bot.handlers.help import router as help_router
from app.bot.handlers.month import router as month_router
from app.bot.handlers.upcoming import router as upcoming_router
from app.bot.handlers.exchange_handler import router as exchange_router
from app.bot.handlers.capture import router as capture_router
from app.bot.handlers.inline_actions import router as inline_actions_router
from app.bot.handlers.duplicate_handler import router as duplicate_router
from app.bot.handlers.inbox import router as inbox_router
from app.bot.handlers.balances import router as balances_router
from app.bot.handlers.rules import router as rules_router
from app.bot.handlers.ask import router as ask_router
from app.bot.middlewares.logging import LoggingMiddleware
from app.infrastructure.config.settings import get_settings
from app.infrastructure.logging.logger import configure_logging

log = logging.getLogger(__name__)

_POLLER_LOCK_KEY = "hastlefam:bot:poller"
_POLLER_LOCK_TTL = 60  # seconds
_LOCK_RENEW_INTERVAL = 20  # seconds

# Global refs so _ConflictExitSession can release the lock before os._exit
_global_lock = None
_global_redis = None


async def _release_global_lock():
    """Best-effort lock release before os._exit."""
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
    """Bot session that exits immediately on TelegramConflictError.

    During Railway rolling deploys, the old instance and the new instance
    briefly coexist. Without a Redis lock, both would fight forever over
    the Telegram long-poll connection. Instead, the instance that loses
    the conflict exits immediately (os._exit), which lets Railway restart
    it. By the time it restarts, the old instance is gone and polling succeeds.
    """

    async def make_request(self, bot, method, **kwargs):
        try:
            return await super().make_request(bot, method, **kwargs)
        except TelegramConflictError:
            log.error(
                "TelegramConflictError: another instance is polling. "
                "Exiting so Railway restarts this instance after the conflict clears."
            )
            # Release Redis lock before exiting so the next instance can start immediately
            # instead of waiting for lock TTL (60s) to expire.
            await _release_global_lock()
            os._exit(1)


async def _renew_lock(lock) -> None:
    """Background task: keep the poller lock alive while polling runs."""
    while True:
        await asyncio.sleep(_LOCK_RENEW_INTERVAL)
        try:
            await lock.extend(_POLLER_LOCK_TTL)
        except Exception as exc:
            log.warning("poller lock extend failed: %s", exc)
            break


async def _setup_redis(redis_url: str):
    """Try to connect to Redis and acquire the single-poller lock.

    Returns (redis_client, lock) on success, or (None, None) if Redis
    is unavailable. Bot starts polling either way — Redis failure is
    logged as a warning, not a crash.
    """
    try:
        import redis.asyncio as aioredis
    except ImportError:
        log.warning("redis package not installed — poller lock and idempotency disabled")
        return None, None

    try:
        client = aioredis.from_url(redis_url, decode_responses=True)
        await client.ping()
        lock = client.lock(_POLLER_LOCK_KEY, timeout=_POLLER_LOCK_TTL)
        log.info("acquiring poller lock (will wait up to 70s for stale lock to expire)…")
        acquired = await lock.acquire(blocking=True, blocking_timeout=70)
        if not acquired:
            log.warning("poller lock held by another instance after 70s — exiting without polling")
            await client.aclose()
            return "exit", None  # sentinel: caller should exit
        log.info("poller lock acquired")
        return client, lock
    except Exception as exc:
        log.warning("Redis unavailable (%s) — poller lock disabled", exc)
        return None, None


async def main() -> None:
    settings = get_settings()
    configure_logging(settings.log_level)

    # Suppress noisy APScheduler internal logs
    logging.getLogger("apscheduler").setLevel(logging.WARNING)

    if not settings.telegram_bot_token:
        log.error(
            "TELEGRAM_BOT_TOKEN is not set — bot worker cannot start. "
            "This process belongs to the Worker service only."
        )
        return

    redis_client, lock = await _setup_redis(settings.redis_url)

    # If lock is held by another instance, exit cleanly
    if redis_client == "exit":
        return

    # Store globally so _ConflictExitSession can release before os._exit
    global _global_lock, _global_redis
    _global_lock = lock
    _global_redis = redis_client

    bot = Bot(token=settings.telegram_bot_token, session=_ConflictExitSession())
    dp = Dispatcher()

    # Logging middleware first — always runs, even if idempotency drops the message
    dp.message.middleware(LoggingMiddleware())

    # Delivery idempotency (only when Redis is available)
    if redis_client is not None:
        from app.bot.middlewares.idempotency import IdempotencyMiddleware
        dp.message.middleware(IdempotencyMiddleware(redis_client))

    # Routers: cancel first (must intercept /cancel in any state),
    # then most-specific, catch-all capture last
    dp.include_router(cancel_router)
    dp.include_router(start_router)
    dp.include_router(help_router)
    dp.include_router(month_router)
    dp.include_router(upcoming_router)
    dp.include_router(exchange_router)
    dp.include_router(inline_actions_router)
    dp.include_router(duplicate_router)
    dp.include_router(inbox_router)
    dp.include_router(balances_router)
    dp.include_router(rules_router)
    dp.include_router(ask_router)
    dp.include_router(capture_router)

    # Catch-all error handler — log every unhandled exception from any handler
    @dp.errors()
    async def _error_handler(event: ErrorEvent) -> bool:
        log.error(
            "unhandled exception in handler update_id=%s",
            getattr(event.update, "update_id", "?"),
            exc_info=event.exception,
        )
        return True

    log.info("routers registered: %d", len(dp.sub_routers))

    # Daily status scheduler (10:00 MSK) — start_daily_status_scheduler logs its own message
    try:
        from app.application.jobs.daily_status_job import start_daily_status_scheduler
        start_daily_status_scheduler(bot)
    except ImportError:
        log.info("apscheduler not installed — daily digest disabled")
    except Exception as e:
        log.error("daily digest scheduler failed to start: %s", e, exc_info=True)

    # Fetch FX rates on startup so they're available immediately
    try:
        from app.application.services.fx_service import fetch_and_store_rates
        await fetch_and_store_rates()
    except Exception as e:
        log.warning("startup FX rate fetch failed: %s", e)

    log.info("starting polling")

    renew_task = asyncio.create_task(_renew_lock(lock)) if lock else None
    try:
        await dp.start_polling(bot, drop_pending_updates=False)
    except Exception as exc:
        log.error("bot polling failed: %s", exc, exc_info=True)
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


if __name__ == '__main__':
    asyncio.run(main())
