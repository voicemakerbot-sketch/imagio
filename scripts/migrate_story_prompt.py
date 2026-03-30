"""Add story_prompt column to presets table.

Usage:
    python scripts/migrate_story_prompt.py
"""

import asyncio
import logging
import sys
from pathlib import Path

# Ensure project root is on sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.core.config import settings
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

logger = logging.getLogger("migrate_story_prompt")


async def migrate() -> None:
    engine = create_async_engine(settings.database_url)

    async with engine.begin() as conn:
        # Check if column already exists
        result = await conn.execute(text("PRAGMA table_info(presets)"))
        columns = {row[1] for row in result.fetchall()}

        if "story_prompt" in columns:
            print("Column 'story_prompt' already exists in presets table — nothing to do.")
        else:
            await conn.execute(text("ALTER TABLE presets ADD COLUMN story_prompt TEXT"))
            print("Added 'story_prompt' column to presets table.")

    await engine.dispose()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(migrate())
