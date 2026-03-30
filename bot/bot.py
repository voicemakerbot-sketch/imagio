from __future__ import annotations

import asyncio
import logging

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.client.session.aiohttp import AiohttpSession
from aiogram.enums import ParseMode
from aiogram.types import BotCommand

from app.core.config import settings
from bot.handlers import menu as menu_handlers
from bot.handlers import presets as preset_handlers
from bot.handlers import queue as queue_handlers
from bot.handlers import story as story_handlers
from bot.handlers import subscription as subscription_handlers
from bot.middleware.user_tracking import UserTrackingMiddleware

logger = logging.getLogger(__name__)

# Suppress noisy HTTP transport debug logs
logging.getLogger("httpcore").setLevel(logging.WARNING)
logging.getLogger("httpx").setLevel(logging.WARNING)


def build_bot() -> tuple[Bot, Dispatcher]:
    proxy = settings.resolved_proxy_url
    session_kwargs = {"timeout": settings.telegram_request_timeout}
    if proxy:
        session_kwargs["proxy"] = proxy
    session = AiohttpSession(**session_kwargs)
    bot = Bot(
        token=settings.telegram_bot_token,
        session=session,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    dispatcher = Dispatcher()

    # Track every user in DB on every update
    dispatcher.update.outer_middleware(UserTrackingMiddleware())

    dispatcher.include_router(subscription_handlers.router)
    dispatcher.include_router(preset_handlers.router)
    dispatcher.include_router(story_handlers.router)
    dispatcher.include_router(queue_handlers.router)
    dispatcher.include_router(menu_handlers.router)
    return bot, dispatcher


async def start_bot() -> None:
    bot, dispatcher = build_bot()
    await bot.set_my_commands(
        [BotCommand(command=cmd, description=desc) for cmd, desc in menu_handlers.BOT_COMMANDS]
    )
    me = await bot.get_me()
    logger.info("Starting bot as %s (@%s)", me.full_name, me.username)
    await dispatcher.start_polling(bot, allowed_updates=dispatcher.resolve_used_update_types())


if __name__ == "__main__":
    asyncio.run(start_bot())
