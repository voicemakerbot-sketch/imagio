"""Feature gating system for subscription tiers.

Currently allows all features — the gating infrastructure is ready
for when subscription billing is implemented.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Dict, Set


class Feature(StrEnum):
    GENERATE = "generate"
    EDIT = "edit"
    QUEUE = "queue"
    PRESETS = "presets"
    STORY = "story"


# Valid subscription tiers
VALID_TIERS = ("free", "premium", "pro", "frozen")

# Free tier: 10 generations/day
FREE_DAILY_LIMIT = 10

# Subscription tier → allowed features
TIER_FEATURES: Dict[str, Set[Feature]] = {
    "free": {Feature.GENERATE},
    "premium": {Feature.GENERATE, Feature.EDIT},
    "pro": {Feature.GENERATE, Feature.EDIT, Feature.QUEUE, Feature.PRESETS, Feature.STORY},
    "frozen": set(),  # no access at all
}

# Human-readable tier names
TIER_LABELS: Dict[str, str] = {
    "free": "Free",
    "premium": "Premium ($10)",
    "pro": "Pro ($15)",
    "frozen": "Frozen",
}

# Which tier is required to unlock a given feature
FEATURE_REQUIRED_TIER: Dict[Feature, str] = {
    Feature.GENERATE: "free",
    Feature.EDIT: "premium",
    Feature.QUEUE: "pro",
    Feature.PRESETS: "pro",
    Feature.STORY: "pro",
}


async def get_user_tier(user_id: int) -> str:
    """Return the subscription tier for a user from the DB."""
    from app.db.models import User
    from app.db.session import AsyncSessionFactory
    from sqlalchemy import select

    async with AsyncSessionFactory() as session:
        result = await session.execute(
            select(User.subscription_tier).where(User.telegram_id == user_id)
        )
        tier = result.scalar_one_or_none()
        return tier if tier in VALID_TIERS else "free"


async def check_feature_access(user_id: int, feature: Feature) -> bool:
    """Check whether a user can access a feature based on their subscription tier."""
    tier = await get_user_tier(user_id)
    allowed = TIER_FEATURES.get(tier, set())
    return feature in allowed


async def get_remaining_generations(telegram_id: int) -> int | None:
    """Return remaining generations for today.

    Returns ``None`` for tiers without a daily limit (premium/pro).
    Returns ``0`` for frozen users.
    """
    from app.db.models import User
    from app.db.session import AsyncSessionFactory
    from sqlalchemy import select

    async with AsyncSessionFactory() as session:
        result = await session.execute(
            select(User.subscription_tier, User.daily_generations)
            .where(User.telegram_id == telegram_id)
        )
        row = result.one_or_none()
        if row is None:
            return FREE_DAILY_LIMIT
        tier, used = row
        if tier == "frozen":
            return 0
        if tier in ("premium", "pro"):
            return None  # unlimited
        return max(0, FREE_DAILY_LIMIT - used)


async def check_and_increment_generation(telegram_id: int, count: int = 1) -> tuple[bool, int | None]:
    """Check daily limit and increment counter atomically.

    Returns ``(allowed, remaining)``:
    - allowed=True  → generation can proceed, counter was incremented
    - allowed=False → limit exceeded or frozen, counter unchanged
    - remaining=None → unlimited (premium/pro)
    """
    from app.db.models import User
    from app.db.session import AsyncSessionFactory
    from sqlalchemy import select

    async with AsyncSessionFactory() as session:
        result = await session.execute(
            select(User).where(User.telegram_id == telegram_id)
        )
        user = result.scalar_one_or_none()
        if user is None:
            return False, 0

        tier = user.subscription_tier or "free"
        if tier == "frozen":
            return False, 0
        if tier in ("premium", "pro"):
            # Unlimited — still track for stats
            user.daily_generations += count
            await session.commit()
            return True, None

        # Free tier — enforce limit
        remaining = max(0, FREE_DAILY_LIMIT - user.daily_generations)
        if remaining < count:
            return False, remaining

        user.daily_generations += count
        await session.commit()
        new_remaining = max(0, FREE_DAILY_LIMIT - user.daily_generations)
        return True, new_remaining


async def reset_daily_generations() -> int:
    """Reset daily_generations to 0 for all users. Returns count of affected rows."""
    from app.db.models import User
    from app.db.session import AsyncSessionFactory
    from sqlalchemy import update as sa_update

    async with AsyncSessionFactory() as session:
        result = await session.execute(
            sa_update(User)
            .where(User.daily_generations > 0)
            .values(daily_generations=0)
        )
        await session.commit()
        return result.rowcount  # type: ignore[return-value]


def get_required_tier_label(feature: Feature) -> str:
    """Return the human-readable tier name required to unlock a feature."""
    tier = FEATURE_REQUIRED_TIER.get(feature, "pro")
    return TIER_LABELS.get(tier, tier)
