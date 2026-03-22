"""One-time fix: update presets.user_id from telegram_id to users.id.

The bug: bot handlers passed telegram_id (e.g. 515945325) as Preset.user_id
instead of the internal DB users.id (e.g. 1).

This script finds presets where user_id matches a known telegram_id
and updates them to the correct DB users.id.
"""

import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from sqlalchemy import select, text  # noqa: E402
from app.db.session import AsyncSessionFactory  # noqa: E402


async def main() -> None:
    async with AsyncSessionFactory() as session:
        # Get all users: id → telegram_id mapping
        rows = (await session.execute(text("SELECT id, telegram_id FROM users"))).fetchall()
        tg_to_db = {row[1]: row[0] for row in rows}
        print(f"Users mapping (telegram_id → db_id): {tg_to_db}")

        # Get all presets
        presets = (await session.execute(text("SELECT id, user_id, name FROM presets"))).fetchall()
        print(f"\nPresets before fix:")
        for p in presets:
            print(f"  id={p[0]}, user_id={p[1]}, name={p[2]}")

        fixed = 0
        for p in presets:
            preset_id, preset_user_id, name = p[0], p[1], p[2]
            if preset_user_id in tg_to_db:
                # This user_id is actually a telegram_id — fix it
                correct_id = tg_to_db[preset_user_id]
                if correct_id != preset_user_id:
                    await session.execute(
                        text("UPDATE presets SET user_id = :correct WHERE id = :pid"),
                        {"correct": correct_id, "pid": preset_id},
                    )
                    print(f"  Fixed preset '{name}' (id={preset_id}): user_id {preset_user_id} → {correct_id}")
                    fixed += 1

        await session.commit()
        print(f"\nFixed {fixed} presets.")

        # Verify
        presets_after = (await session.execute(text("SELECT id, user_id, name FROM presets"))).fetchall()
        print(f"\nPresets after fix:")
        for p in presets_after:
            print(f"  id={p[0]}, user_id={p[1]}, name={p[2]}")


if __name__ == "__main__":
    asyncio.run(main())
