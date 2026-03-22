from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI

from sqlalchemy import text

from app.admin import admin_router
from app.api.routes import api_router
from app.core.config import settings
from app.db.session import Base, engine

logger = logging.getLogger(__name__)

# Default subscription plans to seed on startup
_DEFAULT_PLANS = [
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


@asynccontextmanager
async def lifespan(_: FastAPI):
    # Ensure database tables exist before serving requests.
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        logger.info("Database tables ensured")

    # Seed plans in a separate transaction
    async with engine.begin() as conn:
        for plan in _DEFAULT_PLANS:
            existing = await conn.execute(
                text("SELECT id FROM subscription_plans WHERE id = :id"),
                {"id": plan["id"]},
            )
            if not existing.fetchone():
                await conn.execute(
                    text(
                        "INSERT INTO subscription_plans"
                        " (id, name, price, currency, period_days, tier, description, is_active, sort_order, created_at)"
                        " VALUES (:id, :name, :price, :currency, :period_days, :tier, :description, :is_active, :sort_order, CURRENT_TIMESTAMP)"
                    ),
                    plan,
                )
                logger.info("Seeded plan: %s ($%.0f/%s)", plan["name"], plan["price"], plan["tier"])
            else:
                logger.info("Plan %s already exists", plan["id"])

        # Verify
        result = await conn.execute(text("SELECT id, name, is_active FROM subscription_plans"))
        rows = result.fetchall()
        logger.info("Subscription plans in DB: %d — %s", len(rows), [r[0] for r in rows])

    yield


def create_app() -> FastAPI:
    app = FastAPI(title=settings.project_name, lifespan=lifespan)
    app.include_router(api_router, prefix=settings.api_v1_prefix)
    app.include_router(admin_router)

    @app.get("/", tags=["health"])  # noqa: WPS430 simple health check route
    async def root() -> dict[str, str]:
        return {"status": "ok", "service": settings.project_name}

    return app


app = create_app()
