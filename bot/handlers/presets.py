"""Handlers for preset (template) management.

UX: card-based menu where each parameter is a separate button.
User creates a preset with a name, then configures each param from the card.
"""

from __future__ import annotations

import logging

from aiogram import Bot, F, Router
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message

from app.db.session import AsyncSessionFactory
from app.services.feature_access import Feature, check_feature_access, get_required_tier_label
from app.services.presets import (
    MAX_PRESETS_PER_USER,
    activate_preset,
    count_user_presets,
    create_preset,
    deactivate_all_presets,
    delete_preset,
    format_preset_details,
    get_active_preset,
    get_preset_by_id,
    get_user_presets,
    update_preset,
)
from bot.keyboards.main_menu import (
    build_main_menu,
    build_preset_card_keyboard,
    build_preset_list_keyboard,
    build_preset_menu_keyboard,
    build_preset_ratio_keyboard,
    build_preset_variants_keyboard,
)
from bot.localization.messages import get_message

logger = logging.getLogger(__name__)

router = Router(name="presets")


class PresetStates(StatesGroup):
    waiting_name = State()
    editing_name = State()
    editing_style = State()
    editing_story_prompt = State()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _get_user_language(callback_or_message) -> str:
    from bot.handlers.menu import get_user_language
    user = callback_or_message.from_user if hasattr(callback_or_message, "from_user") else None
    return get_user_language(user)


def _is_bot_command(text: str | None) -> bool:
    return bool(text and text.startswith("/"))


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


async def _show_preset_menu(message: Message, lang: str, state: FSMContext, user_id: int) -> None:
    async with AsyncSessionFactory() as session:
        active = await get_active_preset(session, user_id)

    title = get_message("preset.menu_title", lang)
    if active:
        details = format_preset_details(active)
        title += get_message("preset.active", lang).format(name=active.name, details=details)
    else:
        title += get_message("preset.no_active", lang)

    sent = await message.answer(title, reply_markup=build_preset_menu_keyboard(lang))
    await _remember(state, sent)


async def _show_preset_card(message: Message, lang: str, state: FSMContext, preset_id: int, user_id: int) -> None:
    async with AsyncSessionFactory() as session:
        preset = await get_preset_by_id(session, preset_id, user_id)

    if not preset:
        sent = await message.answer(get_message("preset.not_found", lang))
        await _remember(state, sent)
        return

    lines = [f"📄 <b>{preset.name}</b>"]
    if preset.is_active:
        lines.append("🟢 " + get_message("preset.status_active", lang))
    lines.append("")
    lines.append(f"📐 {get_message('preset.label_ratio', lang)}: <b>{preset.aspect_ratio or '—'}</b>")
    lines.append(f"🔢 {get_message('preset.label_variants', lang)}: <b>{preset.num_variants or '—'}</b>")
    style_display = preset.style_suffix or "—"
    if len(style_display) > 60:
        style_display = style_display[:60] + "…"
    lines.append(f"🎨 {get_message('preset.label_style', lang)}: <i>{style_display}</i>")
    story_display = preset.story_prompt or "—"
    if len(story_display) > 60:
        story_display = story_display[:60] + "…"
    lines.append(f"📖 {get_message('preset.label_story_prompt', lang)}: <i>{story_display}</i>")
    lines.append("")
    lines.append(get_message("preset.style_explanation", lang))

    text = "\n".join(lines)
    sent = await message.answer(text, reply_markup=build_preset_card_keyboard(preset_id, preset.is_active, lang))
    await _remember(state, sent)


# ---------------------------------------------------------------------------
# Menu entry
# ---------------------------------------------------------------------------

@router.callback_query(F.data == "menu:presets")
async def handle_presets_menu(callback: CallbackQuery, state: FSMContext) -> None:
    lang = _get_user_language(callback)
    user_id = callback.from_user.id

    if not await check_feature_access(user_id, Feature.PRESETS):
        tier = get_required_tier_label(Feature.PRESETS)
        await callback.answer(get_message("feature.locked", lang).format(tier=tier), show_alert=True)
        return

    await callback.answer()
    await _safe_delete(callback.message)
    await _cleanup(state, callback.bot)
    await state.clear()

    if callback.message:
        await _show_preset_menu(callback.message, lang, state, user_id)


# ---------------------------------------------------------------------------
# Create preset (name only → card)
# ---------------------------------------------------------------------------

@router.callback_query(F.data == "preset:create")
async def handle_preset_create(callback: CallbackQuery, state: FSMContext) -> None:
    lang = _get_user_language(callback)
    user_id = callback.from_user.id

    async with AsyncSessionFactory() as session:
        count = await count_user_presets(session, user_id)
    if count >= MAX_PRESETS_PER_USER:
        await callback.answer(get_message("preset.limit_reached", lang), show_alert=True)
        return

    await callback.answer()
    await _safe_delete(callback.message)
    await _cleanup(state, callback.bot)

    await state.update_data(language=lang)
    await state.set_state(PresetStates.waiting_name)
    if callback.message:
        sent = await callback.message.answer(get_message("preset.ask_name", lang))
        await _remember(state, sent)


@router.message(PresetStates.waiting_name)
async def handle_preset_name_input(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    lang = data.get("language") or _get_user_language(message)

    if _is_bot_command(message.text):
        await state.clear()
        return

    if not message.text:
        sent = await message.answer(get_message("preset.ask_name", lang))
        await _remember(state, sent)
        return

    name = message.text.strip()
    if len(name) > 100:
        sent = await message.answer(get_message("preset.name_too_long", lang))
        await _remember(state, sent)
        return

    await _cleanup(state, message.bot)
    user_id = message.from_user.id

    async with AsyncSessionFactory() as session:
        preset = await create_preset(session, user_id, name)
        await session.commit()
        preset_id = preset.id

    await state.clear()
    await _show_preset_card(message, lang, state, preset_id, user_id)


# ---------------------------------------------------------------------------
# Preset list
# ---------------------------------------------------------------------------

@router.callback_query(F.data == "preset:list")
async def handle_preset_list(callback: CallbackQuery, state: FSMContext) -> None:
    lang = _get_user_language(callback)
    user_id = callback.from_user.id

    await callback.answer()
    await _safe_delete(callback.message)
    await _cleanup(state, callback.bot)

    async with AsyncSessionFactory() as session:
        presets = await get_user_presets(session, user_id)
        preset_data = list(presets)

    if not preset_data:
        if callback.message:
            sent = await callback.message.answer(
                get_message("preset.empty_list", lang),
                reply_markup=build_preset_menu_keyboard(lang),
            )
            await _remember(state, sent)
        return

    if callback.message:
        sent = await callback.message.answer(
            get_message("preset.menu_title", lang),
            reply_markup=build_preset_list_keyboard(preset_data, lang),
        )
        await _remember(state, sent)


# ---------------------------------------------------------------------------
# Preset card (detail)
# ---------------------------------------------------------------------------

@router.callback_query(F.data.startswith("presetselect:"))
async def handle_preset_detail(callback: CallbackQuery, state: FSMContext) -> None:
    lang = _get_user_language(callback)
    user_id = callback.from_user.id
    try:
        preset_id = int(callback.data.split(":", maxsplit=1)[1])
    except ValueError:
        await callback.answer("Invalid", show_alert=True)
        return

    await callback.answer()
    await _safe_delete(callback.message)
    await _cleanup(state, callback.bot)
    await state.clear()

    if callback.message:
        await _show_preset_card(callback.message, lang, state, preset_id, user_id)


# ---------------------------------------------------------------------------
# Edit ratio
# ---------------------------------------------------------------------------

@router.callback_query(F.data.startswith("presetedit_ratio:"))
async def handle_edit_ratio(callback: CallbackQuery, state: FSMContext) -> None:
    lang = _get_user_language(callback)
    try:
        preset_id = int(callback.data.split(":", maxsplit=1)[1])
    except ValueError:
        await callback.answer("Invalid", show_alert=True)
        return

    await callback.answer()
    await _safe_delete(callback.message)
    await _cleanup(state, callback.bot)

    if callback.message:
        sent = await callback.message.answer(
            get_message("preset.ask_ratio", lang),
            reply_markup=build_preset_ratio_keyboard(preset_id, lang),
        )
        await _remember(state, sent)


@router.callback_query(F.data.startswith("presetratio:"))
async def handle_ratio_choice(callback: CallbackQuery, state: FSMContext) -> None:
    lang = _get_user_language(callback)
    user_id = callback.from_user.id
    # format: presetratio:16_9:42  or  presetratio:clear:42
    payload = callback.data.split(":", maxsplit=1)[1]
    parts = payload.rsplit(":", maxsplit=1)
    if len(parts) != 2:
        await callback.answer("Invalid", show_alert=True)
        return

    raw_ratio, raw_id = parts
    try:
        preset_id = int(raw_id)
    except ValueError:
        await callback.answer("Invalid", show_alert=True)
        return

    ratio = None if raw_ratio == "clear" else raw_ratio.replace("_", ":")

    async with AsyncSessionFactory() as session:
        await update_preset(session, preset_id, user_id, aspect_ratio=ratio)
        await session.commit()

    await callback.answer()
    await _safe_delete(callback.message)
    await _cleanup(state, callback.bot)
    await state.clear()

    if callback.message:
        await _show_preset_card(callback.message, lang, state, preset_id, user_id)


# ---------------------------------------------------------------------------
# Edit variants
# ---------------------------------------------------------------------------

@router.callback_query(F.data.startswith("presetedit_var:"))
async def handle_edit_variants(callback: CallbackQuery, state: FSMContext) -> None:
    lang = _get_user_language(callback)
    try:
        preset_id = int(callback.data.split(":", maxsplit=1)[1])
    except ValueError:
        await callback.answer("Invalid", show_alert=True)
        return

    await callback.answer()
    await _safe_delete(callback.message)
    await _cleanup(state, callback.bot)

    if callback.message:
        sent = await callback.message.answer(
            get_message("preset.ask_variants", lang),
            reply_markup=build_preset_variants_keyboard(preset_id, lang),
        )
        await _remember(state, sent)


@router.callback_query(F.data.startswith("presetvar:"))
async def handle_variants_choice(callback: CallbackQuery, state: FSMContext) -> None:
    lang = _get_user_language(callback)
    user_id = callback.from_user.id
    payload = callback.data.split(":", maxsplit=1)[1]
    parts = payload.rsplit(":", maxsplit=1)
    if len(parts) != 2:
        await callback.answer("Invalid", show_alert=True)
        return

    raw_val, raw_id = parts
    try:
        preset_id = int(raw_id)
    except ValueError:
        await callback.answer("Invalid", show_alert=True)
        return

    num = None if raw_val == "clear" else int(raw_val)

    async with AsyncSessionFactory() as session:
        await update_preset(session, preset_id, user_id, num_variants=num)
        await session.commit()

    await callback.answer()
    await _safe_delete(callback.message)
    await _cleanup(state, callback.bot)
    await state.clear()

    if callback.message:
        await _show_preset_card(callback.message, lang, state, preset_id, user_id)


# ---------------------------------------------------------------------------
# Edit style
# ---------------------------------------------------------------------------

@router.callback_query(F.data.startswith("presetedit_style:"))
async def handle_edit_style_start(callback: CallbackQuery, state: FSMContext) -> None:
    lang = _get_user_language(callback)
    try:
        preset_id = int(callback.data.split(":", maxsplit=1)[1])
    except ValueError:
        await callback.answer("Invalid", show_alert=True)
        return

    await callback.answer()
    await _safe_delete(callback.message)
    await _cleanup(state, callback.bot)

    await state.update_data(language=lang, editing_preset_id=preset_id)
    await state.set_state(PresetStates.editing_style)
    if callback.message:
        sent = await callback.message.answer(get_message("preset.ask_style", lang))
        await _remember(state, sent)


@router.message(PresetStates.editing_style)
async def handle_style_input(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    lang = data.get("language") or _get_user_language(message)
    preset_id = data.get("editing_preset_id")
    user_id = message.from_user.id

    if _is_bot_command(message.text):
        await state.clear()
        return

    if not message.text or not preset_id:
        sent = await message.answer(get_message("preset.ask_style", lang))
        await _remember(state, sent)
        return

    await _cleanup(state, message.bot)
    style = message.text.strip()

    async with AsyncSessionFactory() as session:
        await update_preset(session, preset_id, user_id, style_suffix=style)
        await session.commit()

    await state.clear()
    await _show_preset_card(message, lang, state, preset_id, user_id)


@router.callback_query(F.data.startswith("presetclear_style:"))
async def handle_clear_style(callback: CallbackQuery, state: FSMContext) -> None:
    lang = _get_user_language(callback)
    user_id = callback.from_user.id
    try:
        preset_id = int(callback.data.split(":", maxsplit=1)[1])
    except ValueError:
        await callback.answer("Invalid", show_alert=True)
        return

    async with AsyncSessionFactory() as session:
        await update_preset(session, preset_id, user_id, style_suffix=None)
        await session.commit()

    await callback.answer()
    await _safe_delete(callback.message)
    await _cleanup(state, callback.bot)
    await state.clear()

    if callback.message:
        await _show_preset_card(callback.message, lang, state, preset_id, user_id)


# ---------------------------------------------------------------------------
# Edit story prompt
# ---------------------------------------------------------------------------

@router.callback_query(F.data.startswith("presetedit_story:"))
async def handle_edit_story_prompt_start(callback: CallbackQuery, state: FSMContext) -> None:
    lang = _get_user_language(callback)
    try:
        preset_id = int(callback.data.split(":", maxsplit=1)[1])
    except ValueError:
        await callback.answer("Invalid", show_alert=True)
        return

    await callback.answer()
    await _safe_delete(callback.message)
    await _cleanup(state, callback.bot)

    await state.update_data(language=lang, editing_preset_id=preset_id)
    await state.set_state(PresetStates.editing_story_prompt)
    if callback.message:
        sent = await callback.message.answer(get_message("preset.ask_story_prompt", lang))
        await _remember(state, sent)


@router.message(PresetStates.editing_story_prompt)
async def handle_story_prompt_input(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    lang = data.get("language") or _get_user_language(message)
    preset_id = data.get("editing_preset_id")
    user_id = message.from_user.id

    if _is_bot_command(message.text):
        await state.clear()
        return

    if not message.text or not preset_id:
        sent = await message.answer(get_message("preset.ask_story_prompt", lang))
        await _remember(state, sent)
        return

    await _cleanup(state, message.bot)
    story_prompt = message.text.strip()

    async with AsyncSessionFactory() as session:
        await update_preset(session, preset_id, user_id, story_prompt=story_prompt)
        await session.commit()

    await state.clear()
    await _show_preset_card(message, lang, state, preset_id, user_id)


@router.callback_query(F.data.startswith("presetclear_story:"))
async def handle_clear_story_prompt(callback: CallbackQuery, state: FSMContext) -> None:
    lang = _get_user_language(callback)
    user_id = callback.from_user.id
    try:
        preset_id = int(callback.data.split(":", maxsplit=1)[1])
    except ValueError:
        await callback.answer("Invalid", show_alert=True)
        return

    async with AsyncSessionFactory() as session:
        await update_preset(session, preset_id, user_id, story_prompt=None)
        await session.commit()

    await callback.answer()
    await _safe_delete(callback.message)
    await _cleanup(state, callback.bot)
    await state.clear()

    if callback.message:
        await _show_preset_card(callback.message, lang, state, preset_id, user_id)


# ---------------------------------------------------------------------------
# Edit name
# ---------------------------------------------------------------------------

@router.callback_query(F.data.startswith("presetedit_name:"))
async def handle_edit_name_start(callback: CallbackQuery, state: FSMContext) -> None:
    lang = _get_user_language(callback)
    try:
        preset_id = int(callback.data.split(":", maxsplit=1)[1])
    except ValueError:
        await callback.answer("Invalid", show_alert=True)
        return

    await callback.answer()
    await _safe_delete(callback.message)
    await _cleanup(state, callback.bot)

    await state.update_data(language=lang, editing_preset_id=preset_id)
    await state.set_state(PresetStates.editing_name)
    if callback.message:
        sent = await callback.message.answer(get_message("preset.ask_new_name", lang))
        await _remember(state, sent)


@router.message(PresetStates.editing_name)
async def handle_name_input(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    lang = data.get("language") or _get_user_language(message)
    preset_id = data.get("editing_preset_id")
    user_id = message.from_user.id

    if _is_bot_command(message.text):
        await state.clear()
        return

    if not message.text or not preset_id:
        sent = await message.answer(get_message("preset.ask_new_name", lang))
        await _remember(state, sent)
        return

    name = message.text.strip()
    if len(name) > 100:
        sent = await message.answer(get_message("preset.name_too_long", lang))
        await _remember(state, sent)
        return

    await _cleanup(state, message.bot)

    async with AsyncSessionFactory() as session:
        await update_preset(session, preset_id, user_id, name=name)
        await session.commit()

    await state.clear()
    await _show_preset_card(message, lang, state, preset_id, user_id)


# ---------------------------------------------------------------------------
# Activate / Delete / Deactivate / Back
# ---------------------------------------------------------------------------

@router.callback_query(F.data.startswith("presetact:"))
async def handle_preset_activate(callback: CallbackQuery, state: FSMContext) -> None:
    lang = _get_user_language(callback)
    user_id = callback.from_user.id
    try:
        preset_id = int(callback.data.split(":", maxsplit=1)[1])
    except ValueError:
        await callback.answer("Invalid", show_alert=True)
        return

    async with AsyncSessionFactory() as session:
        preset = await activate_preset(session, preset_id, user_id)
        await session.commit()

    if not preset:
        await callback.answer("Not found", show_alert=True)
        return

    await callback.answer()
    await _safe_delete(callback.message)
    await _cleanup(state, callback.bot)

    if callback.message:
        await _show_preset_card(callback.message, lang, state, preset_id, user_id)


@router.callback_query(F.data.startswith("presetdel:"))
async def handle_preset_delete(callback: CallbackQuery, state: FSMContext) -> None:
    lang = _get_user_language(callback)
    user_id = callback.from_user.id
    try:
        preset_id = int(callback.data.split(":", maxsplit=1)[1])
    except ValueError:
        await callback.answer("Invalid", show_alert=True)
        return

    async with AsyncSessionFactory() as session:
        name = await delete_preset(session, preset_id, user_id)
        await session.commit()

    if not name:
        await callback.answer("Not found", show_alert=True)
        return

    await callback.answer()
    await _safe_delete(callback.message)
    await _cleanup(state, callback.bot)

    if callback.message:
        sent = await callback.message.answer(
            get_message("preset.deleted", lang).format(name=name),
            reply_markup=build_main_menu(lang),
        )
        await _remember(state, sent)


@router.callback_query(F.data == "preset:deactivate")
async def handle_preset_deactivate(callback: CallbackQuery, state: FSMContext) -> None:
    lang = _get_user_language(callback)
    user_id = callback.from_user.id

    async with AsyncSessionFactory() as session:
        await deactivate_all_presets(session, user_id)
        await session.commit()

    await callback.answer()
    await _safe_delete(callback.message)
    await _cleanup(state, callback.bot)

    if callback.message:
        sent = await callback.message.answer(
            get_message("preset.deactivated", lang),
            reply_markup=build_main_menu(lang),
        )
        await _remember(state, sent)


@router.callback_query(F.data == "preset:back")
async def handle_preset_back(callback: CallbackQuery, state: FSMContext) -> None:
    lang = _get_user_language(callback)
    await callback.answer()
    await _safe_delete(callback.message)
    await _cleanup(state, callback.bot)
    await state.clear()
    if callback.message:
        sent = await callback.message.answer(
            get_message("start", lang), reply_markup=build_main_menu(lang),
        )
        await _remember(state, sent)
