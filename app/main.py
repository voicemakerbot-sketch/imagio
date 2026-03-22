from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.admin import admin_router
from app.api.routes import api_router
from app.core.config import settings
from app.db.session import Base, engine


@asynccontextmanager
async def lifespan(_: FastAPI):
    # Ensure database tables exist before serving requests.
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
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
