from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from app.core.config import settings


class Base(DeclarativeBase):
    """Base declarative class for all ORM models."""


engine = create_async_engine(
    settings.database_url,
    future=True,
    echo=settings.environment == "development",
)

AsyncSessionFactory = async_sessionmaker(bind=engine, expire_on_commit=False, class_=AsyncSession)


async def get_session() -> AsyncGenerator[AsyncSession, None]:
    """FastAPI dependency that returns an async DB session."""
    async with AsyncSessionFactory() as session:
        yield session
