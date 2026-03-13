import asyncio
from aiogram import Bot, Dispatcher
from app.bot.handlers.start import router as start_router
from app.bot.handlers.help import router as help_router
from app.bot.handlers.capture import router as capture_router
from app.bot.handlers.duplicate_handler import router as duplicate_router
from app.bot.handlers.inline_actions import router as inline_actions_router
from app.bot.middlewares.logging import LoggingMiddleware
from app.infrastructure.config.settings import get_settings
from app.infrastructure.logging.logger import configure_logging


async def main() -> None:
    settings = get_settings()
    configure_logging(settings.log_level)
    bot = Bot(token=settings.telegram_bot_token)
    dp = Dispatcher()
    dp.message.middleware(LoggingMiddleware())
    # Routers: most-specific first, catch-all capture last
    dp.include_router(start_router)
    dp.include_router(help_router)
    dp.include_router(duplicate_router)
    dp.include_router(inline_actions_router)
    dp.include_router(capture_router)
    await dp.start_polling(bot)


if __name__ == '__main__':
    asyncio.run(main())
