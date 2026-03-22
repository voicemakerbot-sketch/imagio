"""Run FastAPI server + Telegram bot in a single asyncio loop.

Usage:
    python scripts/start_all.py
"""

import asyncio
import logging
import sys
from pathlib import Path

import uvicorn

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from datetime import datetime, timedelta, timezone

from app.core.config import settings  # noqa: E402
from bot.bot import start_bot  # noqa: E402


def configure_logging() -> None:
    level = getattr(logging, settings.log_level.upper(), logging.INFO)
    logging.basicConfig(
        level=level,
        format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    )
    logging.getLogger("aiogram").setLevel(level)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    logging.getLogger("httpx").setLevel(logging.WARNING)


async def run_server() -> None:
    """Run uvicorn inside the existing event loop."""
    config = uvicorn.Config(
        "app.main:app",
        host="0.0.0.0",
        port=8000,
        log_level="info",
    )
    server = uvicorn.Server(config)
    await server.serve()


async def daily_reset_scheduler() -> None:
    """Reset daily_generations for all users at midnight UTC every day."""
    logger = logging.getLogger("daily_reset")
    while True:
        now = datetime.now(timezone.utc)
        # Next midnight UTC
        tomorrow = (now + timedelta(days=1)).replace(
            hour=0, minute=0, second=0, microsecond=0,
        )
        wait_seconds = (tomorrow - now).total_seconds()
        logger.info(
            "Next daily reset in %.0f seconds (at %s UTC)",
            wait_seconds,
            tomorrow.strftime("%Y-%m-%d %H:%M"),
        )
        await asyncio.sleep(wait_seconds)

        try:
            from app.services.feature_access import reset_daily_generations

            count = await reset_daily_generations()
            logger.info("Daily reset complete: %d users reset", count)
        except Exception:
            logger.exception("Daily reset failed")


async def subscription_expiration_scheduler() -> None:
    """Check for expired subscriptions every hour."""
    logger = logging.getLogger("subscription_expiration")
    # Wait 60 seconds on startup to let the server initialise
    await asyncio.sleep(60)
    while True:
        try:
            from app.services.subscription_checker import check_expired_subscriptions

            count = await check_expired_subscriptions()
            if count:
                logger.info("Expired %d subscriptions", count)
        except Exception:
            logger.exception("Subscription expiration check failed")

        await asyncio.sleep(3600)  # every hour


async def main() -> None:
    configure_logging()
    logger = logging.getLogger("start_all")
    logger.info("Starting Imagio (server + bot + daily reset) …")

    # Run all concurrently; if server or bot crashes the whole process stops.
    await asyncio.gather(
        run_server(),
        start_bot(),
        daily_reset_scheduler(),
        subscription_expiration_scheduler(),
    )


if __name__ == "__main__":
    asyncio.run(main())
