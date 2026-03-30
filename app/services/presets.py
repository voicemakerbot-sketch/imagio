"""CRUD operations for user presets.

All public functions accept ``telegram_id`` (the Telegram user ID) and
internally resolve it to the database ``users.id`` primary key used by the
``presets.user_id`` foreign key.
"""

from __future__ import annotations

from typing import Optional, Sequence

from sqlalchemy import select, func, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Preset, User

MAX_PRESETS_PER_USER = 10
MAX_NAME_LENGTH = 100


async def resolve_user_id(session: AsyncSession, telegram_id: int) -> int | None:
    """Convert a Telegram user ID to the internal DB ``users.id``.

    Returns ``None`` if the user has not been tracked yet.
    """
    result = await session.execute(
        select(User.id).where(User.telegram_id == telegram_id)
    )
    return result.scalar_one_or_none()


async def _uid(session: AsyncSession, telegram_id: int) -> int:
    """Resolve telegram_id → DB user id, raising if user not found."""
    uid = await resolve_user_id(session, telegram_id)
    if uid is None:
        raise ValueError(f"User with telegram_id={telegram_id} not found in DB")
    return uid


async def get_active_preset(session: AsyncSession, telegram_id: int) -> Preset | None:
    """Return the single active preset for a user, or None."""
    uid = await resolve_user_id(session, telegram_id)
    if uid is None:
        return None
    stmt = select(Preset).where(Preset.user_id == uid, Preset.is_active.is_(True))
    result = await session.execute(stmt)
    return result.scalar_one_or_none()


async def get_user_presets(session: AsyncSession, telegram_id: int) -> Sequence[Preset]:
    """Return all presets for a user, ordered by creation date."""
    uid = await resolve_user_id(session, telegram_id)
    if uid is None:
        return []
    stmt = select(Preset).where(Preset.user_id == uid).order_by(Preset.created_at)
    result = await session.execute(stmt)
    return result.scalars().all()


async def get_preset_by_id(session: AsyncSession, preset_id: int, telegram_id: int) -> Preset | None:
    """Return a specific preset owned by user."""
    uid = await resolve_user_id(session, telegram_id)
    if uid is None:
        return None
    stmt = select(Preset).where(Preset.id == preset_id, Preset.user_id == uid)
    result = await session.execute(stmt)
    return result.scalar_one_or_none()


async def count_user_presets(session: AsyncSession, telegram_id: int) -> int:
    """Return the number of presets a user has."""
    uid = await resolve_user_id(session, telegram_id)
    if uid is None:
        return 0
    stmt = select(func.count()).select_from(Preset).where(Preset.user_id == uid)
    result = await session.execute(stmt)
    return result.scalar_one()


async def deactivate_all_presets(session: AsyncSession, telegram_id: int) -> None:
    """Deactivate all presets for a user."""
    uid = await resolve_user_id(session, telegram_id)
    if uid is None:
        return
    stmt = (
        update(Preset)
        .where(Preset.user_id == uid, Preset.is_active.is_(True))
        .values(is_active=False)
    )
    await session.execute(stmt)
    await session.flush()


async def create_preset(
    session: AsyncSession,
    telegram_id: int,
    name: str,
    *,
    aspect_ratio: Optional[str] = None,
    num_variants: Optional[int] = None,
    style_suffix: Optional[str] = None,
    story_prompt: Optional[str] = None,
) -> Preset:
    """Create a new preset and activate it (deactivating others)."""
    uid = await _uid(session, telegram_id)
    await deactivate_all_presets(session, telegram_id)
    preset = Preset(
        user_id=uid,
        name=name[:MAX_NAME_LENGTH],
        aspect_ratio=aspect_ratio,
        num_variants=num_variants,
        style_suffix=style_suffix,
        story_prompt=story_prompt,
        is_active=True,
    )
    session.add(preset)
    await session.flush()
    await session.refresh(preset)
    return preset


async def activate_preset(session: AsyncSession, preset_id: int, telegram_id: int) -> Preset | None:
    """Activate a preset (deactivating others). Returns the activated preset or None."""
    preset = await get_preset_by_id(session, preset_id, telegram_id)
    if not preset:
        return None
    await deactivate_all_presets(session, telegram_id)
    preset.is_active = True
    await session.flush()
    await session.refresh(preset)
    return preset


async def delete_preset(session: AsyncSession, preset_id: int, telegram_id: int) -> str | None:
    """Delete a preset. Returns the name of deleted preset, or None if not found."""
    preset = await get_preset_by_id(session, preset_id, telegram_id)
    if not preset:
        return None
    name = preset.name
    await session.delete(preset)
    await session.flush()
    return name


async def update_preset(
    session: AsyncSession,
    preset_id: int,
    telegram_id: int,
    **kwargs: object,
) -> Preset | None:
    """Update preset fields. Returns updated preset or None."""
    preset = await get_preset_by_id(session, preset_id, telegram_id)
    if not preset:
        return None
    for key, value in kwargs.items():
        if hasattr(preset, key):
            setattr(preset, key, value)
    await session.flush()
    await session.refresh(preset)
    return preset


def format_preset_details(preset: Preset) -> str:
    """Format preset parameters into a short summary string."""
    parts: list[str] = []
    if preset.aspect_ratio:
        parts.append(preset.aspect_ratio)
    if preset.num_variants:
        parts.append(f"{preset.num_variants} шт")
    if preset.style_suffix:
        suffix_preview = preset.style_suffix[:30]
        if len(preset.style_suffix) > 30:
            suffix_preview += "…"
        parts.append(f'стиль: "{suffix_preview}"')
    if preset.story_prompt:
        sp_preview = preset.story_prompt[:30]
        if len(preset.story_prompt) > 30:
            sp_preview += "…"
        parts.append(f'📖 story prompt')
    return ", ".join(parts) if parts else "без параметрів"
