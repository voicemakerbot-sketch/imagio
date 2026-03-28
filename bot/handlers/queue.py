"""Handlers for batch generation queue."""

from __future__ import annotations

import asyncio
import base64
import logging
from typing import Any, Dict, List
from uuid import uuid4

from aiogram import Bot, F, Router
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import (
    BufferedInputFile,
    CallbackQuery,
    InputMediaPhoto,
    Message,
)

from app.core.config import settings
from app.db.session import AsyncSessionFactory
from app.services.feature_access import (
    Feature,
    FREE_DAILY_LIMIT,
    check_and_increment_generation,
    check_feature_access,
    get_remaining_generations,
    get_required_tier_label,
    get_user_tier,
)
from app.services.presets import format_preset_details, get_active_preset, get_preset_by_id, get_user_presets
from app.services.voiceapi import (
    VoiceAPIError,
    VoiceAPIRateLimitError,
    VoiceAPITaskFailed,
    generate_image,
)
from bot.keyboards.main_menu import (
    build_main_menu,
    build_queue_actions_keyboard,
    build_queue_preset_picker,
    build_ratio_keyboard,
    build_variant_keyboard,
)
from bot.localization.messages import get_message

logger = logging.getLogger(__name__)

router = Router(name="queue")

MAX_QUEUE_PROMPTS = 25
MAX_PROMPT_LENGTH = 4000


class QueueStates(StatesGroup):
    waiting_ratio = State()
    waiting_variants = State()
    waiting_prompts = State()
    running = State()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _get_user_language(callback_or_message) -> str:
    from bot.handlers.menu import get_user_language
    user = callback_or_message.from_user if hasattr(callback_or_message, "from_user") else None
    return get_user_language(user)


async def _safe_delete(msg: Message | None) -> None:
    if not msg:
        return
    try:
        await msg.delete()
    except (TelegramBadRequest, TelegramForbiddenError):
        pass


async def _remember(state: FSMContext, msg: Message | None) -> None:
    if not msg:
        return
    from bot.handlers.menu import remember_service_message
    await remember_service_message(state, msg)


async def _cleanup(state: FSMContext, bot: Bot) -> None:
    from bot.handlers.menu import cleanup_service_messages
    await cleanup_service_messages(state, bot)


def _parse_prompts(text: str) -> List[str]:
    """Split multiline text into individual prompts, stripping empty lines."""
    lines = text.strip().splitlines()
    return [line.strip() for line in lines if line.strip()]


# ---------------------------------------------------------------------------
# Queue entry: menu:queue
# ---------------------------------------------------------------------------

@router.callback_query(F.data == "menu:queue")
async def handle_queue_menu(callback: CallbackQuery, state: FSMContext) -> None:
    lang = _get_user_language(callback)
    user_id = callback.from_user.id

    # Feature gating
    if not await check_feature_access(user_id, Feature.QUEUE):
        tier = get_required_tier_label(Feature.QUEUE)
        await callback.answer(
            get_message("feature.locked", lang).format(tier=tier), show_alert=True,
        )
        return

    # Frozen check
    if await get_user_tier(user_id) == "frozen":
        await callback.answer(
            get_message("feature.frozen", lang), show_alert=True,
        )
        return

    await callback.answer()
    await _safe_delete(callback.message)
    await _cleanup(state, callback.bot)
    await state.clear()

    # Always show preset picker (presets list + manual + create new)
    async with AsyncSessionFactory() as session:
        presets = await get_user_presets(session, user_id)
        preset_list = list(presets)

    text = get_message("queue.pick_preset", lang)
    await state.update_data(language=lang)
    if callback.message:
        sent = await callback.message.answer(
            text,
            reply_markup=build_queue_preset_picker(preset_list, lang),
        )
        await _remember(state, sent)


# ---------------------------------------------------------------------------
# Queue preset picker handlers
# ---------------------------------------------------------------------------

@router.callback_query(F.data.startswith("queue:pick_preset:"))
async def handle_queue_pick_preset(callback: CallbackQuery, state: FSMContext) -> None:
    """User picked an existing preset for the queue."""
    lang = _get_user_language(callback)
    user_id = callback.from_user.id
    try:
        preset_id = int(callback.data.split(":", maxsplit=2)[2])
    except (ValueError, IndexError):
        await callback.answer("Invalid", show_alert=True)
        return

    async with AsyncSessionFactory() as session:
        preset = await get_preset_by_id(session, preset_id, user_id)

    if not preset:
        await callback.answer("Not found", show_alert=True)
        return

    await callback.answer()
    await _safe_delete(callback.message)
    await _cleanup(state, callback.bot)

    details = format_preset_details(preset)
    text = get_message("queue.intro_with_preset", lang).format(
        name=preset.name, details=details,
    )
    await state.update_data(
        language=lang,
        queue_prompts=[],
        queue_ratio=preset.aspect_ratio or "1:1",
        queue_variants=preset.num_variants or 1,
        queue_style=preset.style_suffix,
    )
    await state.set_state(QueueStates.waiting_prompts)
    if callback.message:
        sent = await callback.message.answer(text)
        await _remember(state, sent)


@router.callback_query(F.data == "queue:no_preset")
async def handle_queue_no_preset(callback: CallbackQuery, state: FSMContext) -> None:
    """User chose manual configuration (no preset)."""
    data = await state.get_data()
    lang = data.get("language") or _get_user_language(callback)

    await callback.answer()
    await _safe_delete(callback.message)
    await _cleanup(state, callback.bot)

    await state.update_data(language=lang, queue_prompts=[], queue_style=None)
    await state.set_state(QueueStates.waiting_ratio)
    if callback.message:
        sent = await callback.message.answer(
            get_message("queue.ratio_ask", lang),
            reply_markup=build_ratio_keyboard(),
        )
        await _remember(state, sent)


@router.callback_query(F.data == "queue:new_preset")
async def handle_queue_new_preset(callback: CallbackQuery, state: FSMContext) -> None:
    """Redirect user to create a new preset, then come back."""
    lang = _get_user_language(callback)
    await callback.answer()
    await _safe_delete(callback.message)
    await _cleanup(state, callback.bot)
    await state.clear()
    # Redirect to presets menu — user creates a preset there, then returns to queue
    if callback.message:
        from bot.handlers.presets import handle_preset_create
        # Simulate the preset:create callback
        await handle_preset_create(callback, state)


# ---------------------------------------------------------------------------
# Queue setup (no preset path)
# ---------------------------------------------------------------------------

@router.callback_query(QueueStates.waiting_ratio, F.data.startswith("genratio:"))
async def handle_queue_ratio(callback: CallbackQuery, state: FSMContext) -> None:
    ratio_code = callback.data.split(":", maxsplit=1)[1].replace("_", ":")
    data = await state.get_data()
    lang = data.get("language") or _get_user_language(callback)

    await state.update_data(queue_ratio=ratio_code)
    await state.set_state(QueueStates.waiting_variants)
    await callback.answer()
    await _safe_delete(callback.message)
    if callback.message:
        sent = await callback.message.answer(
            get_message("queue.variants_ask", lang),
            reply_markup=build_variant_keyboard(),
        )
        await _remember(state, sent)


@router.callback_query(QueueStates.waiting_variants, F.data.startswith("genvar:"))
async def handle_queue_variants(callback: CallbackQuery, state: FSMContext) -> None:
    try:
        count = int(callback.data.split(":", maxsplit=1)[1])
    except ValueError:
        await callback.answer("Invalid", show_alert=True)
        return

    data = await state.get_data()
    lang = data.get("language") or _get_user_language(callback)

    await state.update_data(queue_variants=count)
    await state.set_state(QueueStates.waiting_prompts)
    await callback.answer()
    await _safe_delete(callback.message)
    if callback.message:
        sent = await callback.message.answer(get_message("queue.send_prompts", lang))
        await _remember(state, sent)


# ---------------------------------------------------------------------------
# Receive prompts
# ---------------------------------------------------------------------------

@router.message(QueueStates.waiting_prompts)
async def handle_queue_prompts(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    lang = data.get("language") or _get_user_language(message)

    # Don't eat bot commands — let them through
    if message.text and message.text.startswith("/"):
        await state.clear()
        return

    if not message.text:
        sent = await message.answer(get_message("queue.empty", lang))
        await _remember(state, sent)
        return

    existing: List[str] = list(data.get("queue_prompts", []))
    new_prompts = _parse_prompts(message.text)

    if not new_prompts:
        sent = await message.answer(get_message("queue.empty", lang))
        await _remember(state, sent)
        return

    await _cleanup(state, message.bot)

    # Validate and add
    added = 0
    skipped = 0
    too_long_warnings: List[str] = []
    for idx, prompt in enumerate(new_prompts, start=1):
        if len(existing) >= MAX_QUEUE_PROMPTS:
            skipped += len(new_prompts) - idx + 1
            break
        if len(prompt) > MAX_PROMPT_LENGTH:
            too_long_warnings.append(
                get_message("queue.prompt_too_long", lang).format(number=idx)
            )
            skipped += 1
            continue
        existing.append(prompt)
        added += 1

    await state.update_data(queue_prompts=existing)

    # Build response
    parts: List[str] = []
    if skipped and added:
        parts.append(
            get_message("queue.limit_reached", lang).format(added=added, skipped=skipped)
        )
    else:
        parts.append(
            get_message("queue.added", lang).format(count=added, total=len(existing))
        )
    parts.extend(too_long_warnings)
    text = "\n".join(parts)

    sent = await message.answer(text, reply_markup=build_queue_actions_keyboard(lang))
    await _remember(state, sent)


# ---------------------------------------------------------------------------
# Queue actions
# ---------------------------------------------------------------------------

@router.callback_query(F.data == "queue:add_more")
async def handle_queue_add_more(callback: CallbackQuery, state: FSMContext) -> None:
    data = await state.get_data()
    lang = data.get("language") or _get_user_language(callback)

    await callback.answer()
    await _safe_delete(callback.message)
    await _cleanup(state, callback.bot)

    await state.set_state(QueueStates.waiting_prompts)
    if callback.message:
        sent = await callback.message.answer(get_message("queue.send_prompts", lang))
        await _remember(state, sent)


@router.callback_query(F.data == "queue:clear")
async def handle_queue_clear(callback: CallbackQuery, state: FSMContext) -> None:
    data = await state.get_data()
    lang = data.get("language") or _get_user_language(callback)

    await callback.answer()
    await _safe_delete(callback.message)
    await _cleanup(state, callback.bot)
    await state.clear()

    if callback.message:
        sent = await callback.message.answer(
            get_message("start", lang), reply_markup=build_main_menu(lang),
        )
        await _remember(state, sent)


@router.callback_query(F.data == "queue:cancel")
async def handle_queue_cancel(callback: CallbackQuery, state: FSMContext) -> None:
    data = await state.get_data()
    lang = data.get("language") or _get_user_language(callback)

    await callback.answer()
    await _safe_delete(callback.message)
    await _cleanup(state, callback.bot)
    await state.clear()

    if callback.message:
        sent = await callback.message.answer(
            get_message("start", lang), reply_markup=build_main_menu(lang),
        )
        await _remember(state, sent)


@router.callback_query(F.data == "queue:run")
async def handle_queue_run(callback: CallbackQuery, state: FSMContext) -> None:
    data = await state.get_data()
    lang = data.get("language") or _get_user_language(callback)
    prompts: List[str] = list(data.get("queue_prompts", []))
    ratio: str = data.get("queue_ratio", "1:1")
    num_variants: int = data.get("queue_variants", 1)
    style_suffix: str | None = data.get("queue_style")
    user_id = callback.from_user.id

    if not prompts:
        await callback.answer(get_message("queue.empty", lang), show_alert=True)
        return

    # --- Daily limit gate ---
    total_images = len(prompts) * num_variants
    allowed, remaining = await check_and_increment_generation(user_id, total_images)
    if not allowed:
        text = get_message("feature.daily_limit", lang).format(limit=FREE_DAILY_LIMIT)
        if remaining is not None and remaining > 0:
            text = get_message("feature.remaining", lang).format(
                remaining=remaining, limit=FREE_DAILY_LIMIT,
            )
        await callback.answer(text, show_alert=True)
        return

    await callback.answer()
    await _safe_delete(callback.message)
    await _cleanup(state, callback.bot)
    await state.set_state(QueueStates.running)

    message = callback.message
    if not message:
        await state.clear()
        return

    total = len(prompts)
    success = 0

    for idx, prompt in enumerate(prompts, start=1):
        # Build full prompt with style suffix
        full_prompt = f"{prompt}, {style_suffix}" if style_suffix else prompt

        # Show progress
        status_msg: Message | None = None
        try:
            status_msg = await message.answer(
                get_message("queue.progress", lang).format(current=idx, total=total)
            )

            generated_b64 = await generate_image(
                prompt=full_prompt,
                aspect_ratio=ratio,
                generation_mode=settings.voice_api_generation_mode,
                num_images=num_variants,
                user_id=user_id,
            )

            if not generated_b64:
                raise VoiceAPIError("No images in response")

            await _safe_delete(status_msg)

            # Build and send media group
            media_group = []
            for img_idx, image_b64 in enumerate(generated_b64, start=1):
                image_bytes = base64.b64decode(image_b64)
                filename = f"imagio_q_{uuid4().hex}.png"
                file = BufferedInputFile(image_bytes, filename=filename)
                caption = None
                if img_idx == len(generated_b64):
                    caption = f"✅ {idx}/{total} • {ratio}"
                media_group.append(InputMediaPhoto(media=file, caption=caption))

            await message.answer_media_group(
                media_group, request_timeout=settings.telegram_request_timeout,
            )
            success += 1

        except VoiceAPIRateLimitError:
            logger.warning("Queue: rate limit at prompt %d/%d for user %s", idx, total, user_id)
            await _safe_delete(status_msg)
            await message.answer(
                get_message("queue.item_failed", lang).format(current=idx, total=total)
                + "\n" + get_message("generate.error.rate_limit", lang)
            )
        except (VoiceAPITaskFailed, VoiceAPIError) as exc:
            logger.error("Queue: prompt %d/%d failed: %s", idx, total, exc)
            await _safe_delete(status_msg)
            await message.answer(
                get_message("queue.item_failed", lang).format(current=idx, total=total)
            )
        except Exception:
            logger.exception("Queue: prompt %d/%d unexpected error", idx, total)
            await _safe_delete(status_msg)
            await message.answer(
                get_message("queue.item_failed", lang).format(current=idx, total=total)
            )

    # Final summary
    await message.answer(
        get_message("queue.all_done", lang).format(success=success, total=total),
        reply_markup=build_main_menu(lang),
    )
    await state.clear()
