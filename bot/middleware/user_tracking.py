"""Middleware that ensures every Telegram user is saved/updated in the DB.

Runs on EVERY incoming update (message, callback, inline, etc.).
Creates user on first contact, updates username/premium on subsequent ones.
"""

import logging
from datetime import datetime
from typing import Any, Awaitable, Callable, Dict

from aiogram import BaseMiddleware
from aiogram.types import TelegramObject, Update
from sqlalchemy import select

from app.db.models import User
from app.db.session import AsyncSessionFactory

logger = logging.getLogger(__name__)


class UserTrackingMiddleware(BaseMiddleware):
    """Outer middleware — fires before any handler/filter for every update."""

    async def __call__(
        self,
        handler: Callable[[TelegramObject, Dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: Dict[str, Any],
    ) -> Any:
        # Extract the user from whatever update type came in
        user = self._extract_user(event)
        if user and not user.is_bot:
            try:
                await self._ensure_user(user)
            except Exception:
                logger.exception("UserTrackingMiddleware: failed to upsert user %s", user.id)

        return await handler(event, data)

    @staticmethod
    def _extract_user(event: TelegramObject):
        """Pull the originating telegram user from any update type."""
        # event_user is available on Message, CallbackQuery, InlineQuery, etc.
        if hasattr(event, "from_user") and event.from_user:
            return event.from_user
        # For updates that wrap inner objects (e.g. my_chat_member)
        for attr in ("message", "callback_query", "inline_query", "chosen_inline_result",
                      "shipping_query", "pre_checkout_query", "chat_member", "my_chat_member"):
            inner = getattr(event, attr, None)
            if inner and hasattr(inner, "from_user") and inner.from_user:
                return inner.from_user
        return None

    @staticmethod
    async def _ensure_user(tg_user) -> None:
        """Insert or update the user row in the database."""
        async with AsyncSessionFactory() as session:
            stmt = select(User).where(User.telegram_id == tg_user.id)
            result = await session.execute(stmt)
            db_user = result.scalar_one_or_none()

            if db_user is None:
                # New user — create with free tier
                db_user = User(
                    telegram_id=tg_user.id,
                    username=tg_user.username,
                    language=tg_user.language_code or "uk",
                    subscription_tier="free",
                )
                session.add(db_user)
                logger.info("New user registered: %s (@%s)", tg_user.id, tg_user.username)
            else:
                # Existing user — update username if changed
                if db_user.username != tg_user.username:
                    db_user.username = tg_user.username
                    db_user.updated_at = datetime.utcnow()

            await session.commit()
