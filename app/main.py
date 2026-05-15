from __future__ import annotations

import asyncio
import logging
from pathlib import Path

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.client.session.aiohttp import AiohttpSession
from aiogram.enums import ParseMode
from aiogram.fsm.storage.redis import RedisStorage
from redis.asyncio import Redis

from app.bot.handlers import admin, buy, help, language, services, start
from app.bot.middlewares.i18n import I18n, I18nMiddleware
from app.bot.middlewares.throttling import ThrottlingMiddleware
from app.config import get_settings
from app.db.session import SessionLocal, engine
from app.utils.logging import setup_logging


async def main() -> None:
    settings = get_settings()
    setup_logging(settings.log_level)
    redis = Redis.from_url(settings.redis_url, decode_responses=True)
    storage = RedisStorage(redis=redis)
    bot_session = AiohttpSession(proxy=settings.telegram_proxy_url) if settings.telegram_proxy_url else None
    bot = Bot(
        token=settings.bot_token,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
        session=bot_session,
    )
    dp = Dispatcher(storage=storage)
    i18n = I18n(Path("app/bot/i18n"), settings.default_language)

    dp.update.middleware(I18nMiddleware(SessionLocal, settings, i18n))
    dp.message.middleware(ThrottlingMiddleware(redis, default_limit_seconds=1))

    admin.register_admin_filter(settings)
    dp.include_router(admin.router)
    dp.include_router(start.router)
    dp.include_router(language.router)
    dp.include_router(buy.router)
    dp.include_router(services.router)
    dp.include_router(help.router)

    logging.getLogger(__name__).info("Starting bot")
    try:
        await dp.start_polling(
            bot,
            settings=settings,
            sessionmaker=SessionLocal,
            redis=redis,
            i18n=i18n,
        )
    finally:
        await bot.session.close()
        await redis.aclose()
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
