"""Background subscription expiration checker.

Runs periodically (every hour) to find and expire subscriptions past their
expires_at date, switching non-recurring users back to the free tier.
"""

from __future__ import annotations

import logging

from app.db.session import AsyncSessionFactory
from app.services.payment_client import get_wayforpay_client

logger = logging.getLogger(__name__)


async def check_expired_subscriptions() -> int:
    """Check and expire overdue subscriptions. Returns count of expired."""
    from aiogram import Bot

    wfp = get_wayforpay_client()
    if not wfp:
        logger.debug("WayForPay client not configured — skipping expiration check")
        return 0

    # We need a Bot instance for the manager but won't send messages in expiration
    # Create a minimal one; the manager only uses it for declined notifications
    from bot.bot import build_bot
    bot, _ = build_bot()

    try:
        from app.services.subscription_manager import SubscriptionManager

        async with AsyncSessionFactory() as session:
            mgr = SubscriptionManager(session, wfp, bot)
            count = await mgr.check_expired_subscriptions()
            if count:
                logger.info("Expired %d subscriptions", count)
            return count
    finally:
        await bot.session.close()
