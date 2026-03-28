from __future__ import annotations

import asyncio
import base64
import logging
from typing import Any, Dict, List
from uuid import uuid4

from aiogram import Bot, F, Router
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError
from aiogram.filters import Command, CommandStart
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
from app.services.presets import format_preset_details, get_active_preset
from app.services.voiceapi import (
    VoiceAPIError,
    VoiceAPIRateLimitError,
    VoiceAPITaskFailed,
    edit_image,
    generate_image,
)
from bot.keyboards.main_menu import (
    build_edit_selection_keyboard,
    build_generation_menu,
    build_language_keyboard,
    build_main_menu,
    build_ratio_keyboard,
    build_result_actions_keyboard,
    build_variant_keyboard,
)
from bot.localization.messages import LANGUAGE_LABELS, SUPPORTED_LANGUAGES, get_message, normalize_language

logger = logging.getLogger(__name__)

BOT_COMMANDS = (
    ("start", "Головне меню"),
    ("generate", "Створити промт для генерації"),
    ("subscription", "Інформація про підписку"),
    ("help", "Допомога/FAQ"),
    ("language", "Змінити мову"),
)


class ImageCreationStates(StatesGroup):
    waiting_prompt = State()
    waiting_ratio = State()
    waiting_variants = State()
    choosing_edit_image = State()
    waiting_edit_prompt = State()
    waiting_edit_variants = State()


router = Router(name="menu")

USER_LANG_PREFS: Dict[int, str] = {}
LAST_RESULTS: Dict[int, Dict[str, Any]] = {}
MENU_ACTIONS = tuple(command for command, _ in BOT_COMMANDS) + ("queue", "presets")
SERVICE_MESSAGES_KEY = "service_messages"


def get_user_language(user) -> str:
    if user and user.id in USER_LANG_PREFS:
        return USER_LANG_PREFS[user.id]
    lang = normalize_language(user.language_code if user else None)
    if user:
        USER_LANG_PREFS[user.id] = lang
    return lang


def resolve_language(message: Message) -> str:
    return get_user_language(message.from_user)


async def remember_service_message(state: FSMContext, message: Message | None) -> None:
    if not message:
        return
    data = await state.get_data()
    stored = list(data.get(SERVICE_MESSAGES_KEY, []))
    stored.append({"chat_id": message.chat.id, "message_id": message.message_id})
    await state.update_data(**{SERVICE_MESSAGES_KEY: stored})


async def cleanup_service_messages(state: FSMContext, bot: Bot) -> None:
    data = await state.get_data()
    stored = data.get(SERVICE_MESSAGES_KEY, []) or []
    if not stored:
        return

    async def _try_delete(record: dict) -> None:
        try:
            await bot.delete_message(chat_id=record["chat_id"], message_id=record["message_id"])
        except (TelegramBadRequest, TelegramForbiddenError):
            pass

    await asyncio.gather(*(_try_delete(r) for r in stored))
    await state.update_data(**{SERVICE_MESSAGES_KEY: []})


async def safe_delete_message(message: Message | None) -> None:
    """Delete a single message ignoring 'message not found' errors."""
    if not message:
        return
    try:
        await message.delete()
    except (TelegramBadRequest, TelegramForbiddenError):
        pass


# v1 API is synchronous — no progress stages available.
# We show a static "generating…" message instead.


async def respond_to_action(message: Message, action: str, lang: str, state: FSMContext | None = None, user_id: int = 0) -> None:
    if action == "generate":
        # --- Tier / daily-limit gate ---
        if user_id:
            tier = await get_user_tier(user_id)
            if tier == "frozen":
                await message.answer(get_message("feature.frozen", lang))
                return
            remaining = await get_remaining_generations(user_id)
            if remaining is not None and remaining <= 0:
                await message.answer(
                    get_message("feature.daily_limit", lang).format(limit=FREE_DAILY_LIMIT)
                )
                return

        # Check for active preset (only if user has PRESETS access)
        active_preset = None
        if user_id and await check_feature_access(user_id, Feature.PRESETS):
            async with AsyncSessionFactory() as session:
                active_preset = await get_active_preset(session, user_id)

        if active_preset:
            details = format_preset_details(active_preset)
            text = get_message("generate.with_preset", lang).format(
                name=active_preset.name, details=details,
            )
            if state:
                await state.update_data(
                    language=lang,
                    preset_ratio=active_preset.aspect_ratio,
                    preset_variants=active_preset.num_variants,
                    preset_style=active_preset.style_suffix,
                )
                await state.set_state(ImageCreationStates.waiting_prompt)
            sent = await message.answer(text)
            if state:
                await remember_service_message(state, sent)
        else:
            sent = await message.answer(
                get_message("generate.menu.title", lang),
                reply_markup=build_generation_menu(lang),
            )
            if state:
                await remember_service_message(state, sent)
    elif action == "subscription":
        from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text=get_message("menu.subscription", lang), callback_data="menu:subscription")]
        ])
        sent = await message.answer(
            get_message("subscription.cabinet", lang) if get_message("subscription.cabinet", lang) != "subscription.cabinet" else get_message("subscription.stub", lang),
            reply_markup=kb,
        )
        if state:
            await remember_service_message(state, sent)
    elif action == "help":
        await message.answer(get_message("help.stub", lang))
    elif action == "language":
        sent = await message.answer(get_message("language.prompt", lang), reply_markup=build_language_keyboard())
        if state:
            await remember_service_message(state, sent)


async def start_creation_flow(message: Message, lang: str, state: FSMContext) -> None:
    await state.update_data(language=lang)
    await state.set_state(ImageCreationStates.waiting_prompt)
    prompt_message = await message.answer(get_message("generate.prompt.ask", lang))
    await remember_service_message(state, prompt_message)


async def start_edit_flow(message: Message, lang: str, state: FSMContext, user_id: int) -> None:
    last = LAST_RESULTS.get(user_id)
    if not last:
        await message.answer(get_message("generate.actions.unavailable", lang))
        return

    await state.clear()
    await state.update_data(language=lang, prompt=last["prompt"], ratio=last["ratio"])
    images = last.get("images", [])

    if not images:
        await message.answer(get_message("generate.actions.unavailable", lang))
        return

    if len(images) == 1:
        await state.update_data(selected_index=0)
        await prompt_edit_instructions(message, lang, images[0], 0, state)
        return

    await state.set_state(ImageCreationStates.choosing_edit_image)
    sent = await message.answer(
        get_message("generate.edit.choose_image", lang),
        reply_markup=build_edit_selection_keyboard(len(images)),
    )
    await remember_service_message(state, sent)


async def prompt_edit_instructions(
    message: Message,
    lang: str,
    image_b64: str,
    index: int,
    state: FSMContext,
) -> None:
    image_bytes = base64.b64decode(image_b64)
    filename = f"imagio_prev_{uuid4().hex}.png"
    preview_msg = await message.answer_photo(
        BufferedInputFile(image_bytes, filename=filename),
        caption=get_message("generate.edit.selected", lang).format(number=index + 1),
    )
    await remember_service_message(state, preview_msg)
    ask_msg = await message.answer(get_message("generate.edit.prompt.ask", lang))
    await remember_service_message(state, ask_msg)
    example_msg = await message.answer(get_message("generate.edit.prompt.example", lang))
    await remember_service_message(state, example_msg)
    await state.update_data(selected_index=index)
    await state.set_state(ImageCreationStates.waiting_edit_prompt)


@router.message(CommandStart())
async def handle_start(message: Message, state: FSMContext) -> None:
    await cleanup_service_messages(state, message.bot)
    await state.clear()
    lang = resolve_language(message)
    sent = await message.answer(
        get_message("start", lang),
        reply_markup=build_main_menu(lang),
    )
    await remember_service_message(state, sent)


@router.message(Command("generate"))
async def handle_generate_command(message: Message, state: FSMContext) -> None:
    lang = resolve_language(message)
    await cleanup_service_messages(state, message.bot)
    await state.clear()
    await respond_to_action(message, "generate", lang, state)


@router.message(Command("subscription"))
async def handle_subscription_command(message: Message, state: FSMContext) -> None:
    lang = resolve_language(message)
    await cleanup_service_messages(state, message.bot)
    await state.clear()
    await respond_to_action(message, "subscription", lang, state)


@router.message(Command("help"))
async def handle_help_command(message: Message, state: FSMContext) -> None:
    lang = resolve_language(message)
    await cleanup_service_messages(state, message.bot)
    await state.clear()
    await respond_to_action(message, "help", lang, state)


@router.message(Command("language"))
async def handle_language_command(message: Message, state: FSMContext) -> None:
    lang = resolve_language(message)
    await cleanup_service_messages(state, message.bot)
    await state.clear()
    await respond_to_action(message, "language", lang, state)


@router.callback_query(F.data.startswith("menu:"))
async def handle_menu_callback(callback: CallbackQuery, state: FSMContext) -> None:
    _, action = callback.data.split(":", maxsplit=1)
    if action not in MENU_ACTIONS:
        await callback.answer("Unknown action", show_alert=True)
        return
    lang = get_user_language(callback.from_user)
    await callback.answer()
    await safe_delete_message(callback.message)
    await cleanup_service_messages(state, callback.bot)
    await state.clear()
    if callback.message:
        await respond_to_action(callback.message, action, lang, state, user_id=callback.from_user.id)


@router.callback_query(F.data == "genmenu:create")
async def handle_generation_create(callback: CallbackQuery, state: FSMContext) -> None:
    lang = get_user_language(callback.from_user)
    await callback.answer()
    await safe_delete_message(callback.message)
    await cleanup_service_messages(state, callback.bot)
    await state.clear()
    if callback.message:
        await start_creation_flow(callback.message, lang, state)


@router.callback_query(F.data == "genmenu:edit")
async def handle_generation_edit(callback: CallbackQuery, state: FSMContext) -> None:
    lang = get_user_language(callback.from_user)
    await callback.answer()
    await safe_delete_message(callback.message)
    await cleanup_service_messages(state, callback.bot)
    if callback.message:
        await start_edit_flow(callback.message, lang, state, callback.from_user.id)


@router.callback_query(F.data == "genmenu:mix")
async def handle_generation_mix(callback: CallbackQuery) -> None:
    lang = get_user_language(callback.from_user)
    await callback.answer(get_message("generate.mix.stub", lang), show_alert=True)


@router.callback_query(F.data == "genmenu:back")
async def handle_generation_back(callback: CallbackQuery, state: FSMContext) -> None:
    lang = get_user_language(callback.from_user)
    await callback.answer()
    await safe_delete_message(callback.message)
    await cleanup_service_messages(state, callback.bot)
    await state.clear()
    if callback.message:
        sent = await callback.message.answer(
            get_message("start", lang), reply_markup=build_main_menu(lang),
        )
        await remember_service_message(state, sent)


async def _run_single_generation(
    message: Message,
    state: FSMContext,
    lang: str,
    prompt: str,
    ratio: str,
    count: int,
    style_suffix: str | None = None,
    user_id: int = 0,
) -> None:
    """Run a single image generation (used when preset provides all params)."""
    # --- Daily limit gate ---
    if user_id:
        allowed, remaining = await check_and_increment_generation(user_id, count)
        if not allowed:
            if remaining == 0:
                tier = await get_user_tier(user_id)
                if tier == "frozen":
                    await message.answer(get_message("feature.frozen", lang))
                else:
                    await message.answer(
                        get_message("feature.daily_limit", lang).format(limit=FREE_DAILY_LIMIT)
                    )
            else:
                await message.answer(
                    get_message("feature.daily_limit", lang).format(limit=FREE_DAILY_LIMIT)
                )
            await state.clear()
            return
        if remaining is not None:
            await message.answer(
                get_message("feature.remaining", lang).format(
                    remaining=remaining, limit=FREE_DAILY_LIMIT,
                )
            )

    full_prompt = f"{prompt}, {style_suffix}" if style_suffix else prompt
    bot = message.bot

    status_message: Message | None = None
    try:
        status_message = await message.answer(
            get_message("generate.processing.submitted", lang)
        )

        generated_b64 = await generate_image(
            prompt=full_prompt,
            aspect_ratio=ratio,
            generation_mode=settings.voice_api_generation_mode,
            num_images=count,
            user_id=user_id,
        )

        if not generated_b64:
            raise VoiceAPIError("No images in API response")

        await safe_delete_message(status_message)

        media_group = []
        for idx, image_b64 in enumerate(generated_b64, start=1):
            image_bytes = base64.b64decode(image_b64)
            filename = f"imagio_{uuid4().hex}.png"
            file = BufferedInputFile(image_bytes, filename=filename)
            caption = None
            if idx == len(generated_b64):
                caption = get_message("generate.caption", lang).format(
                    current=idx, total=len(generated_b64), ratio=ratio,
                )
            media_group.append(InputMediaPhoto(media=file, caption=caption))

        await message.answer_media_group(
            media_group, request_timeout=settings.telegram_request_timeout,
        )

        LAST_RESULTS[message.from_user.id] = {
            "prompt": prompt,
            "ratio": ratio,
            "images": generated_b64,
        }

        await message.answer(
            get_message("generate.actions.title", lang),
            reply_markup=build_result_actions_keyboard(lang),
        )
    except VoiceAPIRateLimitError:
        logger.warning("Rate limit for user %s", user_id)
        await safe_delete_message(status_message)
        await message.answer(get_message("generate.error.rate_limit", lang))
    except VoiceAPITaskFailed as exc:
        logger.error("Generation task failed: %s", exc)
        await safe_delete_message(status_message)
        await message.answer(get_message("generate.error", lang))
    except Exception:
        logger.exception("Image generation failed")
        await safe_delete_message(status_message)
        await message.answer(get_message("generate.error", lang))
    finally:
        await state.clear()


@router.message(ImageCreationStates.waiting_prompt)
async def handle_prompt_input(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    lang = data.get("language") or resolve_language(message)

    # Don't eat bot commands — let them through
    if message.text and message.text.startswith("/"):
        await state.clear()
        return

    if not message.text:
        await message.answer(get_message("generate.prompt.empty", lang))
        return
    # Clean up bot's 'describe your image' prompt
    await cleanup_service_messages(state, message.bot)
    await state.update_data(prompt=message.text.strip())

    # If preset provides ratio and variants, skip those steps
    preset_ratio = data.get("preset_ratio")
    preset_variants = data.get("preset_variants")

    if preset_ratio and preset_variants:
        # Both set — go straight to generation
        await state.update_data(ratio=preset_ratio)
        await state.set_state(ImageCreationStates.waiting_variants)
        # Simulate variant choice by triggering generation directly
        await _run_single_generation(
            message, state, lang,
            prompt=message.text.strip(),
            ratio=preset_ratio,
            count=preset_variants,
            style_suffix=data.get("preset_style"),
            user_id=message.from_user.id,
        )
        return
    elif preset_ratio:
        # Ratio set, ask variants
        await state.update_data(ratio=preset_ratio)
        await state.set_state(ImageCreationStates.waiting_variants)
        variants_message = await message.answer(
            get_message("generate.variants.ask", lang),
            reply_markup=build_variant_keyboard(),
        )
        await remember_service_message(state, variants_message)
        return

    # No preset params — normal flow
    await state.set_state(ImageCreationStates.waiting_ratio)
    ratio_message = await message.answer(
        get_message("generate.ratio.ask", lang),
        reply_markup=build_ratio_keyboard(),
    )
    await remember_service_message(state, ratio_message)


@router.callback_query(ImageCreationStates.waiting_ratio, F.data.startswith("genratio:"))
async def handle_ratio_choice(callback: CallbackQuery, state: FSMContext) -> None:
    ratio_code = callback.data.split(":", maxsplit=1)[1].replace("_", ":")
    data = await state.get_data()
    lang = data.get("language") or get_user_language(callback.from_user)
    await state.update_data(ratio=ratio_code)
    await state.set_state(ImageCreationStates.waiting_variants)
    await callback.answer()
    await safe_delete_message(callback.message)
    if callback.message:
        variants_message = await callback.message.answer(
            get_message("generate.variants.ask", lang),
            reply_markup=build_variant_keyboard(),
        )
        await remember_service_message(state, variants_message)


@router.callback_query(ImageCreationStates.waiting_variants, F.data.startswith("genvar:"))
async def handle_variant_choice(callback: CallbackQuery, state: FSMContext) -> None:
    try:
        count = int(callback.data.split(":", maxsplit=1)[1])
    except ValueError:
        await callback.answer("Invalid selection", show_alert=True)
        return

    data = await state.get_data()
    lang = data.get("language") or get_user_language(callback.from_user)
    prompt = data.get("prompt")
    ratio = data.get("ratio")
    bot = callback.bot
    await callback.answer()
    await safe_delete_message(callback.message)
    await cleanup_service_messages(state, bot)

    message = callback.message
    if not message or not prompt or not ratio:
        await state.clear()
        if message:
            await message.answer(get_message("generate.error", lang))
        return

    # --- Daily limit gate ---
    allowed, remaining = await check_and_increment_generation(callback.from_user.id, count)
    if not allowed:
        if remaining == 0:
            tier = await get_user_tier(callback.from_user.id)
            if tier == "frozen":
                await message.answer(get_message("feature.frozen", lang))
            else:
                await message.answer(
                    get_message("feature.daily_limit", lang).format(limit=FREE_DAILY_LIMIT)
                )
        else:
            await message.answer(
                get_message("feature.daily_limit", lang).format(limit=FREE_DAILY_LIMIT)
            )
        await state.clear()
        return
    if remaining is not None:
        await message.answer(
            get_message("feature.remaining", lang).format(
                remaining=remaining, limit=FREE_DAILY_LIMIT,
            )
        )

    # Apply style suffix from preset if present
    style_suffix = data.get("preset_style")
    full_prompt = f"{prompt}, {style_suffix}" if style_suffix else prompt

    status_message: Message | None = None
    try:
        status_message = await message.answer(
            get_message("generate.processing.submitted", lang)
        )

        generated_b64 = await generate_image(
            prompt=full_prompt,
            aspect_ratio=ratio,
            generation_mode=settings.voice_api_generation_mode,
            num_images=count,
            user_id=callback.from_user.id,
        )

        if not generated_b64:
            raise VoiceAPIError("No images in API response")

        # Delete progress bar before sending results
        await safe_delete_message(status_message)

        # Build media group
        media_group = []
        for idx, image_b64 in enumerate(generated_b64, start=1):
            image_bytes = base64.b64decode(image_b64)
            filename = f"imagio_{uuid4().hex}.png"
            file = BufferedInputFile(image_bytes, filename=filename)
            caption = None
            if idx == len(generated_b64):
                caption = get_message("generate.caption", lang).format(
                    current=idx, total=len(generated_b64), ratio=ratio
                )
            media_group.append(InputMediaPhoto(media=file, caption=caption))

        await message.answer_media_group(
            media_group, request_timeout=settings.telegram_request_timeout
        )

        LAST_RESULTS[callback.from_user.id] = {
            "prompt": prompt,
            "ratio": ratio,
            "images": generated_b64,
        }

        await message.answer(
            get_message("generate.actions.title", lang),
            reply_markup=build_result_actions_keyboard(lang),
        )
    except VoiceAPIRateLimitError:
        logger.warning("All API keys exhausted for user %s", callback.from_user.id)
        await safe_delete_message(status_message)
        await message.answer(get_message("generate.error.rate_limit", lang))
    except VoiceAPITaskFailed as exc:
        logger.error("Generation task failed: %s", exc)
        await safe_delete_message(status_message)
        await message.answer(get_message("generate.error", lang))
    except Exception:
        logger.exception("Image generation failed")
        await safe_delete_message(status_message)
        await message.answer(get_message("generate.error", lang))
    finally:
        await state.clear()


@router.callback_query(F.data == "result:regen")
async def handle_result_regenerate(callback: CallbackQuery, state: FSMContext) -> None:
    lang = get_user_language(callback.from_user)
    last = LAST_RESULTS.get(callback.from_user.id)
    if not last:
        await callback.answer(get_message("generate.actions.unavailable", lang), show_alert=True)
        return

    await callback.answer()
    await safe_delete_message(callback.message)
    await cleanup_service_messages(state, callback.bot)
    await state.clear()

    source_image = last.get("source_image")
    if source_image:
        # This was an edit result — regenerate via edit_image
        await state.update_data(
            language=lang,
            edit_prompt=last["prompt"],
            ratio=last["ratio"],
            source_b64=source_image,
        )
        await state.set_state(ImageCreationStates.waiting_edit_variants)
    else:
        # This was a fresh generation — regenerate via generate_image
        await state.update_data(language=lang, prompt=last["prompt"], ratio=last["ratio"])
        await state.set_state(ImageCreationStates.waiting_variants)

    if callback.message:
        sent = await callback.message.answer(
            get_message("generate.regen.prompt", lang),
            reply_markup=build_variant_keyboard(),
        )
        await remember_service_message(state, sent)


@router.callback_query(F.data == "result:edit")
async def handle_result_edit(callback: CallbackQuery, state: FSMContext) -> None:
    lang = get_user_language(callback.from_user)
    last = LAST_RESULTS.get(callback.from_user.id)
    if not last:
        await callback.answer(get_message("generate.actions.unavailable", lang), show_alert=True)
        return

    await callback.answer()
    await safe_delete_message(callback.message)
    await cleanup_service_messages(state, callback.bot)
    if callback.message:
        await start_edit_flow(callback.message, lang, state, callback.from_user.id)


@router.callback_query(F.data == "result:new")
async def handle_result_new(callback: CallbackQuery, state: FSMContext) -> None:
    """Start a brand new generation from scratch."""
    lang = get_user_language(callback.from_user)
    await callback.answer()
    await safe_delete_message(callback.message)
    await cleanup_service_messages(state, callback.bot)
    await state.clear()
    if callback.message:
        await start_creation_flow(callback.message, lang, state)


@router.callback_query(ImageCreationStates.choosing_edit_image, F.data.startswith("editselect:"))
async def handle_edit_selection(callback: CallbackQuery, state: FSMContext) -> None:
    try:
        index = int(callback.data.split(":", maxsplit=1)[1])
    except ValueError:
        await callback.answer("Invalid selection", show_alert=True)
        return

    lang = get_user_language(callback.from_user)
    last = LAST_RESULTS.get(callback.from_user.id)
    images = (last or {}).get("images", [])
    if index < 0 or index >= len(images):
        await callback.answer("Invalid image", show_alert=True)
        return

    await callback.answer()
    await safe_delete_message(callback.message)
    await cleanup_service_messages(state, callback.bot)
    if callback.message:
        await prompt_edit_instructions(callback.message, lang, images[index], index, state)


@router.message(ImageCreationStates.waiting_edit_prompt)
async def handle_edit_prompt(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    lang = data.get("language") or resolve_language(message)

    # Don't eat bot commands
    if message.text and message.text.startswith("/"):
        await state.clear()
        return

    if not message.text:
        await message.answer(get_message("generate.edit.prompt.empty", lang))
        return

    edit_prompt = message.text.strip()
    selected_index = data.get("selected_index", 0)

    # Validate source image exists
    last = LAST_RESULTS.get(message.from_user.id)
    images = (last or {}).get("images", [])
    if not images or selected_index >= len(images):
        await message.answer(get_message("generate.actions.unavailable", lang))
        await state.clear()
        return

    # Cleanup bot preview/instruction messages
    await cleanup_service_messages(state, message.bot)

    # Save edit prompt and transition to variant selection
    await state.update_data(edit_prompt=edit_prompt, source_b64=images[selected_index])
    await state.set_state(ImageCreationStates.waiting_edit_variants)
    sent = await message.answer(
        get_message("generate.variants.ask", lang),
        reply_markup=build_variant_keyboard(),
    )
    await remember_service_message(state, sent)


@router.callback_query(ImageCreationStates.waiting_edit_variants, F.data.startswith("genvar:"))
async def handle_edit_variant_choice(callback: CallbackQuery, state: FSMContext) -> None:
    try:
        count = int(callback.data.split(":", maxsplit=1)[1])
    except ValueError:
        await callback.answer("Invalid selection", show_alert=True)
        return

    data = await state.get_data()
    lang = data.get("language") or get_user_language(callback.from_user)
    edit_prompt = data.get("edit_prompt", "")
    ratio = data.get("ratio", "1:1")
    source_b64 = data.get("source_b64", "")

    bot = callback.bot
    await callback.answer()
    await safe_delete_message(callback.message)
    await cleanup_service_messages(state, bot)

    message = callback.message
    if not message or not edit_prompt or not source_b64:
        await state.clear()
        if message:
            await message.answer(get_message("generate.error", lang))
        return

    status_message: Message | None = None
    try:
        status_message = await message.answer(
            get_message("generate.processing.submitted", lang)
        )

        generated_b64 = await edit_image(
            edit_instruction=edit_prompt,
            reference_image_b64=source_b64,
            aspect_ratio=ratio,
            generation_mode=settings.voice_api_generation_mode,
            num_images=count,
            user_id=callback.from_user.id,
        )

        if not generated_b64:
            raise VoiceAPIError("No images in edit API response")

        await safe_delete_message(status_message)

        media_group = []
        for idx, image_b64 in enumerate(generated_b64, start=1):
            image_bytes_out = base64.b64decode(image_b64)
            filename = f"imagio_edit_{uuid4().hex}.png"
            file = BufferedInputFile(image_bytes_out, filename=filename)
            caption = None
            if idx == len(generated_b64):
                caption = get_message("generate.caption", lang).format(
                    current=idx, total=len(generated_b64), ratio=ratio
                )
            media_group.append(InputMediaPhoto(media=file, caption=caption))

        await message.answer_media_group(
            media_group, request_timeout=settings.telegram_request_timeout
        )

        # Save results with source_image so regenerate keeps editing context
        LAST_RESULTS[callback.from_user.id] = {
            "prompt": edit_prompt,
            "ratio": ratio,
            "images": generated_b64,
            "source_image": source_b64,
        }

        await message.answer(
            get_message("generate.actions.title", lang),
            reply_markup=build_result_actions_keyboard(lang),
        )
    except VoiceAPIRateLimitError:
        logger.warning("All API keys exhausted for user %s", callback.from_user.id)
        await safe_delete_message(status_message)
        await message.answer(get_message("generate.error.rate_limit", lang))
    except VoiceAPITaskFailed as exc:
        logger.error("Edit task failed: %s", exc)
        await safe_delete_message(status_message)
        await message.answer(get_message("generate.error", lang))
    except Exception:
        logger.exception("Image edit failed")
        await safe_delete_message(status_message)
        await message.answer(get_message("generate.error", lang))
    finally:
        await state.clear()


@router.callback_query(F.data.startswith("set_lang:"))
async def handle_language_switch(callback: CallbackQuery, state: FSMContext) -> None:
    user = callback.from_user
    _, code = callback.data.split(":", maxsplit=1)
    if code not in SUPPORTED_LANGUAGES:
        await callback.answer("Unsupported language", show_alert=True)
        return

    if user:
        USER_LANG_PREFS[user.id] = code

    await callback.answer()
    await safe_delete_message(callback.message)
    await cleanup_service_messages(state, callback.bot)
    if callback.message:
        sent = await callback.message.answer(
            get_message("language.updated", code).format(language=LANGUAGE_LABELS[code]),
            reply_markup=build_main_menu(code),
        )
        await remember_service_message(state, sent)
