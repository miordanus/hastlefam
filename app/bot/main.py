import asyncio
import logging

import redis.asyncio as aioredis
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
from app.bot.middlewares.idempotency import IdempotencyMiddleware
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


async def main() -> None:
    settings = get_settings()
    configure_logging(settings.log_level)

    redis_client = aioredis.from_url(settings.redis_url, decode_responses=True)

    # Layer A: single active poller lock — prevents duplicate polling during deploy overlap
    lock = redis_client.lock(_POLLER_LOCK_KEY, timeout=_POLLER_LOCK_TTL)
    acquired = await lock.acquire(blocking=False)
    if not acquired:
        log.warning("poller lock held by another instance — exiting without polling")
        await redis_client.aclose()
        return

    bot = Bot(token=settings.telegram_bot_token)
    dp = Dispatcher()

    # Layer B: delivery idempotency — drop duplicate deliveries of the same update
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

    renew_task = asyncio.create_task(_renew_lock(lock))
    try:
        await dp.start_polling(bot)
    finally:
        renew_task.cancel()
        try:
            await lock.release()
        except Exception:
            pass
        await redis_client.aclose()


if __name__ == '__main__':
    asyncio.run(main())
