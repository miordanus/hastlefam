import asyncio
import logging

from aiogram import Bot, Dispatcher
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
from app.bot.middlewares.logging import LoggingMiddleware
from app.infrastructure.config.settings import get_settings
from app.infrastructure.logging.logger import configure_logging

log = logging.getLogger(__name__)

_POLLER_LOCK_KEY = "hastlefam:bot:poller"
_POLLER_LOCK_TTL = 60  # seconds
_LOCK_RENEW_INTERVAL = 20  # seconds


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
        # Quick connectivity check
        await client.ping()
        lock = client.lock(_POLLER_LOCK_KEY, timeout=_POLLER_LOCK_TTL)
        acquired = await lock.acquire(blocking=False)
        if not acquired:
            log.warning("poller lock held by another instance — exiting without polling")
            await client.aclose()
            return "exit", None  # sentinel: caller should exit
        log.info("poller lock acquired")
        return client, lock
    except Exception as exc:
        log.warning("Redis unavailable (%s) — poller lock and idempotency disabled", exc)
        return None, None


async def main() -> None:
    settings = get_settings()
    configure_logging(settings.log_level)

    redis_client, lock = await _setup_redis(settings.redis_url)

    # If lock is held by another instance, exit cleanly
    if redis_client == "exit":
        return

    bot = Bot(token=settings.telegram_bot_token)
    dp = Dispatcher()

    # Layer B: delivery idempotency (only when Redis is available)
    if redis_client is not None:
        from app.bot.middlewares.idempotency import IdempotencyMiddleware
        dp.message.middleware(IdempotencyMiddleware(redis_client))

    dp.message.middleware(LoggingMiddleware())

    # Routers: most-specific first, catch-all capture last
    dp.include_router(start_router)
    dp.include_router(help_router)
    dp.include_router(month_router)
    dp.include_router(upcoming_router)
    dp.include_router(exchange_router)
    dp.include_router(inline_actions_router)
    dp.include_router(duplicate_router)
    dp.include_router(inbox_router)
    dp.include_router(balances_router)
    dp.include_router(capture_router)

    # Daily status scheduler (10:00 MSK)
    try:
        from app.application.jobs.daily_status_job import start_daily_status_scheduler
        start_daily_status_scheduler(bot)
        log.info("daily digest scheduler started (10:00 MSK)")
    except ImportError:
        log.info("apscheduler not installed — daily digest disabled")
    except Exception as e:
        log.error("daily digest scheduler failed to start: %s", e, exc_info=True)

    log.info("starting polling")

    renew_task = asyncio.create_task(_renew_lock(lock)) if lock else None
    try:
        await dp.start_polling(bot)
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
