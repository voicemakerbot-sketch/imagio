"""Story-to-Images parser service.

Breaks a story into visual scenes via OpenAI GPT and returns
image-generation prompts for each scene.

System constraints (scene count, JSON format) are hardcoded.
Users can only influence style via their preset's ``story_prompt`` field.
"""

from __future__ import annotations

import json
import logging
from typing import Any, Dict, List, Optional

import httpx

from app.core.config import settings

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

MAX_STORY_LENGTH = 150_000  # characters
MIN_SCENES = 10
MAX_SCENES = 30
VARIANTS_PER_SCENE = 2

# ---------------------------------------------------------------------------
# System prompt — hardcoded, cannot be overridden by user
# ---------------------------------------------------------------------------

_SYSTEM_PROMPT = """\
You are an expert visual storyteller. Your task is to break a story into \
key visual scenes and write image generation prompts for each scene.

STRICT RULES (non-negotiable):
1. Break the story into exactly {target_scenes} scenes, evenly distributed \
across the narrative (beginning, middle, end).
2. RESPOND ONLY with valid JSON object. No markdown, no explanation.
3. Format:
{{
  "characters": [
    {{"name": "...", "visual": "detailed physical appearance: age, gender, \
hair color/style, eye color, skin tone, build, distinguishing features, \
typical clothing"}}
  ],
  "scenes": [
    {{"scene": 1, "prompt": "..."}}
  ]
}}

CHARACTER CONSISTENCY (critical):
- First, identify ALL named characters from the story and write a detailed \
visual identity for each in the "characters" array.
- In EVERY scene prompt, when a character appears, include their FULL visual \
description from the characters array — do NOT use just a name.
- A character must look IDENTICAL across all scenes: same hair, same face, \
same build, same clothing (unless the story explicitly changes it).
- Example: instead of "John walks in the park", write \
"a tall man in his 30s with short brown hair, green eyes, wearing a dark \
blue coat and jeans, walks through a sunlit park"

{style_instructions}

USER INSTRUCTIONS:
{user_style_prompt}
"""

DEFAULT_STORY_PROMPT = """\
Each scene must capture a KEY VISUAL MOMENT — something that would make \
a compelling illustration.
Write prompts in English, regardless of the story language.
Each prompt must be a self-contained detailed visual description (100-200 words).\
"""

# Hard-coded style/quality rules always appended — cannot be overridden by user
_STYLE_INSTRUCTIONS = """\
PROMPT QUALITY RULES:
- Each prompt must include: characters' full appearance (from characters array), \
pose, expression, environment, lighting, mood, camera angle, composition.
- Each prompt is SELF-CONTAINED — do not say "same as before" or reference \
other scenes. Repeat the full visual description every time.
- DO NOT include text, speech bubbles, watermarks, or UI elements.
- DO NOT mention character names — only visual descriptions.\
"""


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def calculate_target_scenes(text_length: int) -> int:
    """Adaptive scene count: clamp(length / 1500, MIN_SCENES, MAX_SCENES)."""
    raw = text_length / 1500
    return max(MIN_SCENES, min(MAX_SCENES, round(raw)))


async def parse_story(
    story_text: str,
    *,
    target_scenes: Optional[int] = None,
    story_prompt: Optional[str] = None,
    style_suffix: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """Parse story into visual scenes via OpenAI.

    Args:
        story_text: Full story text (max 150K chars).
        target_scenes: Override scene count (auto-calculated if None).
        story_prompt: User's custom instructions for GPT scene parsing.
                      Falls back to DEFAULT_STORY_PROMPT if empty.
        style_suffix: Style from preset, appended to each image prompt.

    Returns:
        List of dicts: [{"scene": 1, "prompt": "..."}, ...]

    Raises:
        RuntimeError: If OpenAI API key is missing or API returns error.
        ValueError: If story is too long or GPT returns invalid response.
    """
    api_key = settings.openai_api_key
    model = settings.openai_model

    if not api_key:
        raise RuntimeError("OPENAI_API_KEY not configured")

    if len(story_text) > MAX_STORY_LENGTH:
        raise ValueError(
            f"Story too long: {len(story_text):,} chars (max {MAX_STORY_LENGTH:,})"
        )

    if target_scenes is None:
        target_scenes = calculate_target_scenes(len(story_text))

    user_style = (story_prompt or "").strip() or DEFAULT_STORY_PROMPT

    style_block = _STYLE_INSTRUCTIONS
    if style_suffix:
        style_block += f"\n\nVISUAL STYLE (apply to ALL scenes): {style_suffix}"

    system_msg = _SYSTEM_PROMPT.format(
        target_scenes=target_scenes,
        user_style_prompt=user_style,
        style_instructions=style_block,
    )

    user_msg = (
        f"Break this story into exactly {target_scenes} visual scenes "
        f"and write image generation prompts.\n\nSTORY:\n{story_text}"
    )

    logger.info(
        "story_parser: %d chars → target %d scenes, model=%s",
        len(story_text), target_scenes, model,
    )

    async with httpx.AsyncClient(timeout=180.0) as client:
        resp = await client.post(
            "https://api.openai.com/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            json={
                "model": model,
                "messages": [
                    {"role": "system", "content": system_msg},
                    {"role": "user", "content": user_msg},
                ],
                "temperature": 0.7,
                "response_format": {"type": "json_object"},
            },
        )

    if resp.status_code != 200:
        raise RuntimeError(f"OpenAI API error {resp.status_code}: {resp.text[:300]}")

    body = resp.json()
    content = body["choices"][0]["message"]["content"]
    usage = body.get("usage", {})

    logger.info(
        "story_parser: %d prompt tokens, %d completion tokens",
        usage.get("prompt_tokens", 0),
        usage.get("completion_tokens", 0),
    )

    # Parse JSON
    parsed = json.loads(content)
    if isinstance(parsed, dict):
        scenes = parsed.get("scenes", parsed.get("result", []))
    elif isinstance(parsed, list):
        scenes = parsed
    else:
        raise ValueError(f"Unexpected GPT response format: {type(parsed)}")

    if not scenes:
        raise ValueError("GPT returned empty scenes list")

    logger.info("story_parser: parsed %d scenes", len(scenes))
    return scenes
