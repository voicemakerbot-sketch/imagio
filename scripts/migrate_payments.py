"""Migration script: create Payment, SubscriptionPlan tables + extend Subscription.

Also seeds the two default plans (premium_monthly, pro_monthly).

Usage:
    python scripts/migrate_payments.py
"""

import asyncio
import logging
import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from sqlalchemy import inspect, text

from app.core.config import settings  # noqa: E402
from app.db.session import engine  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")
logger = logging.getLogger("migrate_payments")


async def migrate() -> None:
    """Run the migration."""
    async with engine.begin() as conn:
        # ── 1. Create subscription_plans table ────────────────────
        await conn.execute(text("""
            CREATE TABLE IF NOT EXISTS subscription_plans (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                price REAL NOT NULL,
                currency TEXT NOT NULL DEFAULT 'USD',
                period_days INTEGER NOT NULL DEFAULT 30,
                tier TEXT NOT NULL,
                description TEXT,
                is_active INTEGER NOT NULL DEFAULT 1,
                sort_order INTEGER NOT NULL DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """))
        logger.info("✅ subscription_plans table ensured")

        # ── 2. Create payments table ──────────────────────────────
        await conn.execute(text("""
            CREATE TABLE IF NOT EXISTS payments (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL REFERENCES users(id),
                order_reference TEXT NOT NULL UNIQUE,
                amount REAL NOT NULL,
                currency TEXT NOT NULL DEFAULT 'USD',
                plan_id TEXT REFERENCES subscription_plans(id),
                status TEXT NOT NULL DEFAULT 'pending',
                provider TEXT NOT NULL DEFAULT 'wayforpay',
                card_pan TEXT,
                card_type TEXT,
                telegram_message_id INTEGER,
                webhook_payload TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """))
        logger.info("✅ payments table ensured")

        # ── 3. Add index on payments.order_reference ──────────────
        await conn.execute(text("""
            CREATE INDEX IF NOT EXISTS ix_payments_order_reference
            ON payments(order_reference)
        """))

        # ── 4. Extend subscriptions table with new columns ───────
        # SQLite doesn't support IF NOT EXISTS for ALTER TABLE,
        # so we check column existence first.
        columns = await conn.run_sync(
            lambda sync_conn: [c["name"] for c in inspect(sync_conn).get_columns("subscriptions")]
        )

        alter_columns = {
            "plan_id": "TEXT REFERENCES subscription_plans(id)",
            "is_recurring": "INTEGER NOT NULL DEFAULT 0",
            "regular_order_id": "TEXT",
            "retry_count": "INTEGER NOT NULL DEFAULT 0",
            "activation_type": "TEXT NOT NULL DEFAULT 'free'",
            "cancelled_at": "TIMESTAMP",
        }

        for col_name, col_def in alter_columns.items():
            if col_name not in columns:
                await conn.execute(text(
                    f"ALTER TABLE subscriptions ADD COLUMN {col_name} {col_def}"
                ))
                logger.info("  + Added column subscriptions.%s", col_name)
            else:
                logger.info("  ⏭ Column subscriptions.%s already exists", col_name)

        # ── 5. Seed default plans ─────────────────────────────────
        existing = await conn.execute(text("SELECT id FROM subscription_plans"))
        existing_ids = {row[0] for row in existing.fetchall()}

        plans = [
            {
                "id": "premium_monthly",
                "name": "Premium",
                "price": 10.0,
                "currency": "USD",
                "period_days": 30,
                "tier": "premium",
                "description": "Unlimited generations + edit mode",
                "is_active": 1,
                "sort_order": 1,
            },
            {
                "id": "pro_monthly",
                "name": "Pro",
                "price": 15.0,
                "currency": "USD",
                "period_days": 30,
                "tier": "pro",
                "description": "Unlimited generations + edit + queue + presets",
                "is_active": 1,
                "sort_order": 2,
            },
        ]

        for plan in plans:
            if plan["id"] not in existing_ids:
                await conn.execute(text("""
                    INSERT INTO subscription_plans
                        (id, name, price, currency, period_days, tier, description, is_active, sort_order)
                    VALUES
                        (:id, :name, :price, :currency, :period_days, :tier, :description, :is_active, :sort_order)
                """), plan)
                logger.info("  + Seeded plan: %s ($%.0f/%s)", plan["name"], plan["price"], plan["tier"])
            else:
                logger.info("  ⏭ Plan %s already exists", plan["id"])

    logger.info("🎉 Migration complete!")


if __name__ == "__main__":
    asyncio.run(migrate())
