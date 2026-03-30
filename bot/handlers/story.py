"""Handlers for Story-to-Images feature.

Flow:
1. User clicks 📖 in main menu → picks a preset (or none)
2. Sends story text (or .txt file)
3. Bot parses story into scenes via GPT
4. Generates 2 image variants per scene via VoiceAPI
5. Sends results as document files grouped by scene
"""

from __future__ import annotations

import asyncio
import base64
import logging
from typing import Any, Dict, Optional

from aiogram import Bot, F, Router
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import (
    BufferedInputFile,
    CallbackQuery,
    InputMediaDocument,
    Message,
)

from app.db.session import AsyncSessionFactory
from app.services.feature_access import (
    Feature,
    check_feature_access,
    get_required_tier_label,
    get_user_tier,
)
from app.services.presets import (
    format_preset_details,
    get_active_preset,
    get_preset_by_id,
    get_user_presets,
)
from app.services.story_parser import (
    MAX_STORY_LENGTH,
    VARIANTS_PER_SCENE,
    calculate_target_scenes,
    parse_story,
)
from app.services.voiceapi import (
    VoiceAPIError,
    VoiceAPIRateLimitError,
    VoiceAPITaskFailed,
    generate_image,
)
from bot.keyboards.main_menu import (
    build_main_menu,
    build_story_cancel_keyboard,
    build_story_preset_picker,
)
from bot.localization.messages import get_message

logger = logging.getLogger(__name__)

router = Router(name="story")

MIN_STORY_LENGTH = 500


class StoryStates(StatesGroup):
    waiting_text = State()
    generating = State()


# ---------------------------------------------------------------------------
# Helpers (reuse from menu module)
# ---------------------------------------------------------------------------

def _get_lang(callback_or_message) -> str:
    from bot.handlers.menu import get_user_language
    user = (
        callback_or_message.from_user
        if hasattr(callback_or_message, "from_user")
        else None
    )
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


# ---------------------------------------------------------------------------
# Entry point: menu:story callback (dispatched from menu handler)
# ---------------------------------------------------------------------------

@router.callback_query(F.data == "menu:story")
async def handle_story_entry(callback: CallbackQuery, state: FSMContext) -> None:
    """Entry point from main menu."""
    lang = _get_lang(callback)
    user_id = callback.from_user.id
    await callback.answer()
    await _safe_delete(callback.message)
    await _cleanup(state, callback.bot)
    await state.clear()

    # Feature gate: Pro only
    if not await check_feature_access(user_id, Feature.STORY):
        tier_label = get_required_tier_label(Feature.STORY)
        await callback.message.answer(
            get_message("feature.locked", lang).format(tier=tier_label),
            reply_markup=build_main_menu(lang),
        )
        return

    # Show preset picker
    async with AsyncSessionFactory() as session:
        presets = await get_user_presets(session, user_id)

    sent = await callback.message.answer(
        get_message("story.pick_preset", lang),
        reply_markup=build_story_preset_picker(list(presets), lang),
    )
    await _remember(state, sent)
    await state.update_data(language=lang)


# ---------------------------------------------------------------------------
# Preset selection
# ---------------------------------------------------------------------------

@router.callback_query(F.data.startswith("story:pick_preset:"))
async def handle_story_pick_preset(callback: CallbackQuery, state: FSMContext) -> None:
    """User picked a specific preset for story generation."""
    lang = _get_lang(callback)
    preset_id = int(callback.data.split(":")[-1])
    user_id = callback.from_user.id
    await callback.answer()
    await _safe_delete(callback.message)

    async with AsyncSessionFactory() as session:
        preset = await get_preset_by_id(session, preset_id, user_id)

    if not preset:
        await callback.message.answer(get_message("preset.not_found", lang))
        return

    await state.update_data(
        language=lang,
        preset_id=preset.id,
        preset_ratio=preset.aspect_ratio or "1:1",
        preset_style=preset.style_suffix,
        preset_story_prompt=preset.story_prompt,
    )
    await state.set_state(StoryStates.waiting_text)

    sent = await callback.message.answer(
        get_message("story.send_text", lang),
        reply_markup=build_story_cancel_keyboard(lang),
    )
    await _remember(state, sent)


@router.callback_query(F.data == "story:no_preset")
async def handle_story_no_preset(callback: CallbackQuery, state: FSMContext) -> None:
    """User chose to proceed without a preset."""
    lang = _get_lang(callback)
    await callback.answer()
    await _safe_delete(callback.message)

    await state.update_data(
        language=lang,
        preset_id=None,
        preset_ratio="1:1",
        preset_style=None,
        preset_story_prompt=None,
    )
    await state.set_state(StoryStates.waiting_text)

    sent = await callback.message.answer(
        get_message("story.send_text", lang),
        reply_markup=build_story_cancel_keyboard(lang),
    )
    await _remember(state, sent)


@router.callback_query(F.data == "story:cancel")
async def handle_story_cancel(callback: CallbackQuery, state: FSMContext) -> None:
    """Return to main menu."""
    lang = _get_lang(callback)
    await callback.answer()
    await _safe_delete(callback.message)
    await _cleanup(state, callback.bot)
    await state.clear()
    await callback.message.answer(
        get_message("start", lang),
        reply_markup=build_main_menu(lang),
    )


# ---------------------------------------------------------------------------
# Receive story text (text message or .txt document)
# ---------------------------------------------------------------------------

@router.message(StoryStates.waiting_text, F.document)
async def handle_story_document(message: Message, state: FSMContext, bot: Bot) -> None:
    """Accept a .txt file as story input."""
    lang = _get_lang(message)

    doc = message.document
    if not doc.file_name or not doc.file_name.lower().endswith(".txt"):
        sent = await message.answer(
            "⚠️ Підтримуються лише <code>.txt</code> файли.",
            reply_markup=build_story_cancel_keyboard(lang),
        )
        await _remember(state, sent)
        return

    if doc.file_size and doc.file_size > 1_000_000:  # 1MB safety limit
        sent = await message.answer(
            get_message("story.too_long", lang).format(length="1MB+", max=MAX_STORY_LENGTH),
            reply_markup=build_story_cancel_keyboard(lang),
        )
        await _remember(state, sent)
        return

    file = await bot.download(doc)
    story_text = file.read().decode("utf-8", errors="replace")
    await _process_story(message, state, bot, story_text, lang)


@router.message(StoryStates.waiting_text, F.text)
async def handle_story_text(message: Message, state: FSMContext, bot: Bot) -> None:
    """Accept story as plain text message."""
    lang = _get_lang(message)

    if message.text.startswith("/"):
        return  # let other handlers process commands

    await _process_story(message, state, bot, message.text, lang)


# ---------------------------------------------------------------------------
# Core processing pipeline
# ---------------------------------------------------------------------------

async def _process_story(
    message: Message,
    state: FSMContext,
    bot: Bot,
    story_text: str,
    lang: str,
) -> None:
    """Parse story → generate images → send results."""
    user_id = message.from_user.id
    data = await state.get_data()

    # Validate length
    if len(story_text) > MAX_STORY_LENGTH:
        sent = await message.answer(
            get_message("story.too_long", lang).format(
                length=f"{len(story_text):,}", max=f"{MAX_STORY_LENGTH:,}",
            ),
            reply_markup=build_story_cancel_keyboard(lang),
        )
        await _remember(state, sent)
        return

    if len(story_text) < MIN_STORY_LENGTH:
        sent = await message.answer(
            get_message("story.too_short", lang),
            reply_markup=build_story_cancel_keyboard(lang),
        )
        await _remember(state, sent)
        return

    # Switch to generating state to prevent duplicate submissions
    await state.set_state(StoryStates.generating)

    target_scenes = calculate_target_scenes(len(story_text))

    # Phase 1: Parse story
    status_msg = await message.answer(
        get_message("story.parsing", lang).format(scenes=target_scenes),
    )

    try:
        scenes = await parse_story(
            story_text,
            target_scenes=target_scenes,
            story_prompt=data.get("preset_story_prompt"),
            style_suffix=data.get("preset_style"),
        )
    except (RuntimeError, ValueError) as exc:
        logger.error("Story parse failed for user %s: %s", user_id, exc)
        await _safe_delete(status_msg)
        await message.answer(
            get_message("story.parse_error", lang),
            reply_markup=build_main_menu(lang),
        )
        await state.clear()
        return
    except Exception:
        logger.exception("Unexpected error parsing story for user %s", user_id)
        await _safe_delete(status_msg)
        await message.answer(
            get_message("story.parse_error", lang),
            reply_markup=build_main_menu(lang),
        )
        await state.clear()
        return

    total_scenes = len(scenes)

    # Update status: parsed
    try:
        await status_msg.edit_text(
            get_message("story.parsed", lang).format(
                count=total_scenes, variants=VARIANTS_PER_SCENE,
            ),
        )
    except TelegramBadRequest:
        pass

    # Phase 2: Generate images
    aspect_ratio = data.get("preset_ratio", "1:1")
    success_count = 0

    for idx, scene in enumerate(scenes, 1):
        prompt = scene.get("prompt", "")
        if not prompt:
            continue

        # Update progress
        try:
            await status_msg.edit_text(
                get_message("story.generating", lang).format(
                    current=idx, total=total_scenes,
                ),
            )
        except TelegramBadRequest:
            pass

        try:
            images_b64 = await generate_image(
                prompt=prompt,
                aspect_ratio=aspect_ratio,
                generation_mode="quality",
                num_images=VARIANTS_PER_SCENE,
                user_id=user_id,
            )

            # Send variants as documents (files)
            media_group = []
            for v_idx, img_b64 in enumerate(images_b64, 1):
                img_bytes = base64.b64decode(img_b64)
                filename = f"scene_{idx:02d}_v{v_idx}.png"
                caption = get_message("story.scene_caption", lang).format(
                    scene=idx, total=total_scenes,
                    variant=v_idx, variants=VARIANTS_PER_SCENE,
                )
                media_group.append(
                    InputMediaDocument(
                        media=BufferedInputFile(img_bytes, filename=filename),
                        caption=caption if v_idx == 1 else None,
                    )
                )

            if media_group:
                await bot.send_media_group(
                    chat_id=message.chat.id,
                    media=media_group,
                )

            success_count += 1

            # Small delay between scenes for fair scheduling
            await asyncio.sleep(0.5)

        except (VoiceAPIRateLimitError, VoiceAPITaskFailed, VoiceAPIError) as exc:
            logger.warning(
                "Story scene %d/%d failed for user %s: %s",
                idx, total_scenes, user_id, exc,
            )
            try:
                await status_msg.edit_text(
                    get_message("story.scene_failed", lang).format(
                        current=idx, total=total_scenes,
                    ),
                )
            except TelegramBadRequest:
                pass
            await asyncio.sleep(1)
            continue
        except Exception:
            logger.exception(
                "Unexpected error on story scene %d/%d for user %s",
                idx, total_scenes, user_id,
            )
            continue

    # Phase 3: Done
    await _safe_delete(status_msg)
    await message.answer(
        get_message("story.all_done", lang).format(
            success=success_count, total=total_scenes,
        ),
        reply_markup=build_main_menu(lang),
    )
    await state.clear()
