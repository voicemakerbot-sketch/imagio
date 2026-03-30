from __future__ import annotations

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from bot.localization.messages import LANGUAGE_LABELS, SUPPORTED_LANGUAGES, get_message

ASPECT_RATIOS = ("16:9", "9:16", "3:2", "2:3", "4:3", "3:4", "1:1")


def build_main_menu(language: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=get_message("menu.generate", language), callback_data="menu:generate")],
            [InlineKeyboardButton(text=get_message("menu.story", language), callback_data="menu:story")],
            [InlineKeyboardButton(text=get_message("menu.queue", language), callback_data="menu:queue")],
            [InlineKeyboardButton(text=get_message("menu.presets", language), callback_data="menu:presets")],
            [InlineKeyboardButton(text=get_message("menu.subscription", language), callback_data="menu:subscription")],
            [InlineKeyboardButton(text=get_message("menu.help", language), callback_data="menu:help")],
            [InlineKeyboardButton(text=get_message("menu.language", language), callback_data="menu:language")],
        ]
    )


def build_generation_menu(language: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=get_message("generate.menu.create", language), callback_data="genmenu:create")],
            [InlineKeyboardButton(text=get_message("generate.menu.edit", language), callback_data="genmenu:edit")],
            [InlineKeyboardButton(text=get_message("generate.menu.mix", language), callback_data="genmenu:mix")],
            [InlineKeyboardButton(text=get_message("generate.menu.back", language), callback_data="genmenu:back")],
        ]
    )


def build_language_keyboard() -> InlineKeyboardMarkup:
    rows = []
    for code in SUPPORTED_LANGUAGES:
        rows.append([InlineKeyboardButton(text=LANGUAGE_LABELS[code], callback_data=f"set_lang:{code}")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def build_ratio_keyboard() -> InlineKeyboardMarkup:
    rows = []
    for idx in range(0, len(ASPECT_RATIOS), 3):
        chunk = ASPECT_RATIOS[idx : idx + 3]
        rows.append(
            [InlineKeyboardButton(text=ratio, callback_data=f"genratio:{ratio.replace(':', '_')}") for ratio in chunk]
        )
    return InlineKeyboardMarkup(inline_keyboard=rows)


def build_variant_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=str(i), callback_data=f"genvar:{i}") for i in range(1, 5)]
        ]
    )


def build_result_actions_keyboard(language: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=get_message("generate.actions.regenerate", language), callback_data="result:regen")],
            [InlineKeyboardButton(text=get_message("generate.actions.edit", language), callback_data="result:edit")],
            [InlineKeyboardButton(text=get_message("generate.actions.new", language), callback_data="result:new")],
        ]
    )


def build_edit_selection_keyboard(count: int) -> InlineKeyboardMarkup:
    rows = []
    buttons = [InlineKeyboardButton(text=str(idx + 1), callback_data=f"editselect:{idx}") for idx in range(count)]
    for idx in range(0, len(buttons), 3):
        rows.append(buttons[idx : idx + 3])
    return InlineKeyboardMarkup(inline_keyboard=rows)


# ---------------------------------------------------------------------------
# Queue keyboards
# ---------------------------------------------------------------------------


def build_queue_actions_keyboard(language: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text=get_message("queue.add_more", language), callback_data="queue:add_more"),
                InlineKeyboardButton(text=get_message("queue.run", language), callback_data="queue:run"),
            ],
            [
                InlineKeyboardButton(text=get_message("queue.clear", language), callback_data="queue:clear"),
                InlineKeyboardButton(text=get_message("queue.cancel", language), callback_data="queue:cancel"),
            ],
        ]
    )


def build_queue_preset_picker(presets: list, language: str) -> InlineKeyboardMarkup:
    """Picker shown at queue entry: existing presets + manual + create new."""
    rows = []
    for p in presets:
        prefix = "🟢 " if p.is_active else ""
        rows.append([
            InlineKeyboardButton(
                text=f"{prefix}{p.name}",
                callback_data=f"queue:pick_preset:{p.id}",
            )
        ])
    rows.append([
        InlineKeyboardButton(
            text=get_message("queue.no_preset", language),
            callback_data="queue:no_preset",
        )
    ])
    rows.append([
        InlineKeyboardButton(
            text=get_message("queue.new_preset", language),
            callback_data="queue:new_preset",
        )
    ])
    rows.append([
        InlineKeyboardButton(
            text=get_message("queue.cancel", language),
            callback_data="queue:cancel",
        )
    ])
    return InlineKeyboardMarkup(inline_keyboard=rows)


# ---------------------------------------------------------------------------
# Preset keyboards
# ---------------------------------------------------------------------------


def build_preset_menu_keyboard(language: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=get_message("preset.create", language), callback_data="preset:create")],
            [InlineKeyboardButton(text=get_message("preset.list", language), callback_data="preset:list")],
            [InlineKeyboardButton(text=get_message("preset.deactivate", language), callback_data="preset:deactivate")],
            [InlineKeyboardButton(text=get_message("preset.back", language), callback_data="preset:back")],
        ]
    )


def build_preset_list_keyboard(presets: list, language: str) -> InlineKeyboardMarkup:
    rows = []
    for p in presets:
        prefix = "🟢 " if p.is_active else ""
        rows.append(
            [InlineKeyboardButton(text=f"{prefix}{p.name}", callback_data=f"presetselect:{p.id}")]
        )
    rows.append(
        [InlineKeyboardButton(text=get_message("preset.back", language), callback_data="menu:presets")]
    )
    return InlineKeyboardMarkup(inline_keyboard=rows)


def build_preset_card_keyboard(preset_id: int, is_active: bool, language: str) -> InlineKeyboardMarkup:
    """Card-style keyboard: one button per parameter + actions."""
    rows = [
        [InlineKeyboardButton(
            text=f"📐 {get_message('preset.btn_ratio', language)}",
            callback_data=f"presetedit_ratio:{preset_id}",
        )],
        [InlineKeyboardButton(
            text=f"🔢 {get_message('preset.btn_variants', language)}",
            callback_data=f"presetedit_var:{preset_id}",
        )],
        [InlineKeyboardButton(
            text=f"🎨 {get_message('preset.btn_style', language)}",
            callback_data=f"presetedit_style:{preset_id}",
        )],
        [InlineKeyboardButton(
            text=f"🧹 {get_message('preset.btn_clear_style', language)}",
            callback_data=f"presetclear_style:{preset_id}",
        )],
        [InlineKeyboardButton(
            text=f"\u2728\ufe0f {get_message('preset.btn_rename', language)}",
            callback_data=f"presetedit_name:{preset_id}",
        )],
        [InlineKeyboardButton(
            text=f"\ud83d\udcd6 {get_message('preset.btn_story_prompt', language)}",
            callback_data=f"presetedit_story:{preset_id}",
        )],
        [InlineKeyboardButton(
            text=f"\ud83e\uddf9 {get_message('preset.btn_clear_story_prompt', language)}",
            callback_data=f"presetclear_story:{preset_id}",
        )],
    ]
    # Activate / deactivate toggle
    if not is_active:
        rows.append([InlineKeyboardButton(
            text=get_message("preset.activate_btn", language),
            callback_data=f"presetact:{preset_id}",
        )])
    # Delete + back
    rows.append([
        InlineKeyboardButton(
            text=get_message("preset.delete_btn", language),
            callback_data=f"presetdel:{preset_id}",
        ),
        InlineKeyboardButton(
            text=get_message("preset.back_to_list", language),
            callback_data="preset:list",
        ),
    ])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def build_preset_ratio_keyboard(preset_id: int, language: str) -> InlineKeyboardMarkup:
    """Ratio picker that writes back to a specific preset."""
    rows = []
    for idx in range(0, len(ASPECT_RATIOS), 3):
        chunk = ASPECT_RATIOS[idx : idx + 3]
        rows.append([
            InlineKeyboardButton(
                text=ratio,
                callback_data=f"presetratio:{ratio.replace(':', '_')}:{preset_id}",
            )
            for ratio in chunk
        ])
    rows.append([
        InlineKeyboardButton(
            text=f"🧹 {get_message('preset.btn_clear', language)}",
            callback_data=f"presetratio:clear:{preset_id}",
        ),
        InlineKeyboardButton(
            text=get_message("preset.back_to_list", language),
            callback_data=f"presetselect:{preset_id}",
        ),
    ])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def build_preset_variants_keyboard(preset_id: int, language: str) -> InlineKeyboardMarkup:
    """Variant count picker for a specific preset."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text=str(i), callback_data=f"presetvar:{i}:{preset_id}")
                for i in range(1, 5)
            ],
            [
                InlineKeyboardButton(
                    text=f"\ud83e\uddf9 {get_message('preset.btn_clear', language)}",
                    callback_data=f"presetvar:clear:{preset_id}",
                ),
                InlineKeyboardButton(
                    text=get_message("preset.back_to_list", language),
                    callback_data=f"presetselect:{preset_id}",
                ),
            ],
        ]
    )


# ---------------------------------------------------------------------------
# Story-to-Images keyboards
# ---------------------------------------------------------------------------


def build_story_preset_picker(presets: list, language: str) -> InlineKeyboardMarkup:
    """Picker shown at story entry: existing presets + no-preset option."""
    rows = []
    for p in presets:
        prefix = "\ud83d\udfe2 " if p.is_active else ""
        rows.append([
            InlineKeyboardButton(
                text=f"{prefix}{p.name}",
                callback_data=f"story:pick_preset:{p.id}",
            )
        ])
    rows.append([
        InlineKeyboardButton(
            text=get_message("story.no_preset", language),
            callback_data="story:no_preset",
        )
    ])
    rows.append([
        InlineKeyboardButton(
            text=get_message("story.cancel", language),
            callback_data="story:cancel",
        )
    ])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def build_story_cancel_keyboard(language: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(
                text=get_message("story.cancel", language),
                callback_data="story:cancel",
            )]
        ]
    )
