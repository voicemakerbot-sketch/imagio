"""Test script for Story-to-Images feature.

Reads story from test.txt in project root.
Reads user-editable style prompt from story_prompt.txt in project root.
System constraints (scene count, JSON format) are hardcoded — cannot be overridden.

Parses story → shows ALL prompts in console → generates first N scenes (2 variants).

Usage:
    python scripts/test_story_to_images.py              # parse + gen first 3 scenes
    python scripts/test_story_to_images.py --parse-only  # parse only, no images
    python scripts/test_story_to_images.py --gen-scenes 5
    python scripts/test_story_to_images.py --ratio 9:16
    python scripts/test_story_to_images.py --style "cinematic, 8k"
"""

from __future__ import annotations

import argparse
import asyncio
import base64
import json
import logging
import os
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

# Add project root to path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")

import httpx

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger("story_test")

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4o-mini")

VOICE_API_BASE_URL = os.getenv("VOICE_API_BASE_URL", "https://voiceapi.csv666.ru/api")
VOICE_API_KEY = os.getenv("VOICE_API_KEY", "")
VOICE_API_GENERATION_MODE = os.getenv("VOICE_API_GENERATION_MODE", "quality")

MAX_STORY_LENGTH = 150_000  # characters
MIN_SCENES = 10
MAX_SCENES = 30
VARIANTS_PER_SCENE = 2
DEFAULT_GEN_SCENES = 3  # generate images for first N scenes only

STORY_FILE = ROOT / "test.txt"
PROMPT_FILE = ROOT / "story_prompt.txt"
OUTPUT_DIR = ROOT / "data" / "story_output"

# ---------------------------------------------------------------------------
# System prompt — HARDCODED, user cannot override scene count / format
# ---------------------------------------------------------------------------

SYSTEM_PROMPT_TEMPLATE = """\
You are an expert visual storyteller. Your task is to break a story into \
key visual scenes and write image generation prompts for each scene.

STRICT RULES (non-negotiable):
1. Break the story into exactly {target_scenes} scenes, evenly distributed \
across the narrative (beginning, middle, end).
2. RESPOND ONLY with valid JSON object. No markdown, no explanation.
3. Format: {{"scenes": [{{"scene": 1, "prompt": "..."}}, ...]}}

USER STYLE INSTRUCTIONS:
{user_style_prompt}
"""

# ---------------------------------------------------------------------------
# Story Parser (OpenAI GPT-4o-mini)
# ---------------------------------------------------------------------------


def calculate_target_scenes(text_length: int) -> int:
    """Adaptive scene count: clamp(length / 1500, MIN_SCENES, MAX_SCENES)."""
    raw = text_length / 1500
    return max(MIN_SCENES, min(MAX_SCENES, round(raw)))


async def parse_story_to_scenes(
    story_text: str,
    user_style_prompt: str,
    *,
    target_scenes: Optional[int] = None,
    style_suffix: str = "",
) -> List[Dict[str, Any]]:
    """Send story to GPT-4o-mini, get back list of scene prompts.

    System constraints (scene count, JSON format) are hardcoded.
    User can only influence style instructions via story_prompt.txt.
    """
    if not OPENAI_API_KEY:
        raise RuntimeError("OPENAI_API_KEY not set in .env")

    if len(story_text) > MAX_STORY_LENGTH:
        raise ValueError(
            f"Story too long: {len(story_text)} chars (max {MAX_STORY_LENGTH})"
        )

    if target_scenes is None:
        target_scenes = calculate_target_scenes(len(story_text))

    logger.info(
        "Parsing story: %d chars → target %d scenes", len(story_text), target_scenes
    )

    # Build system prompt: hardcoded structure + user style
    system_msg = SYSTEM_PROMPT_TEMPLATE.format(
        target_scenes=target_scenes,
        user_style_prompt=user_style_prompt,
    )

    user_msg = (
        f"Break this story into exactly {target_scenes} visual scenes and "
        f"write image generation prompts.\n\n"
        f"STORY:\n{story_text}"
    )

    async with httpx.AsyncClient(timeout=120.0) as client:
        resp = await client.post(
            "https://api.openai.com/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {OPENAI_API_KEY}",
                "Content-Type": "application/json",
            },
            json={
                "model": OPENAI_MODEL,
                "messages": [
                    {"role": "system", "content": system_msg},
                    {"role": "user", "content": user_msg},
                ],
                "temperature": 0.7,
                "response_format": {"type": "json_object"},
            },
        )

    if resp.status_code != 200:
        raise RuntimeError(f"OpenAI API error {resp.status_code}: {resp.text[:500]}")

    body = resp.json()
    content = body["choices"][0]["message"]["content"]
    usage = body.get("usage", {})

    logger.info(
        "OpenAI: %d prompt tokens, %d completion tokens",
        usage.get("prompt_tokens", 0),
        usage.get("completion_tokens", 0),
    )

    # Parse JSON response
    parsed = json.loads(content)

    # Handle both formats: {"scenes": [...]} or [...]
    if isinstance(parsed, dict):
        scenes = parsed.get("scenes", parsed.get("result", []))
    elif isinstance(parsed, list):
        scenes = parsed
    else:
        raise ValueError(f"Unexpected response format: {type(parsed)}")

    if not scenes:
        raise ValueError("GPT returned empty scenes list")

    # Append style suffix to each prompt if provided
    if style_suffix:
        for scene in scenes:
            scene["prompt"] = f"{scene['prompt']}, {style_suffix}"

    logger.info("Parsed %d scenes from story", len(scenes))
    return scenes


# ---------------------------------------------------------------------------
# Image Generator (VoiceAPI)
# ---------------------------------------------------------------------------


async def generate_scene_images(
    scenes: List[Dict[str, Any]],
    *,
    max_scenes: int = DEFAULT_GEN_SCENES,
    aspect_ratio: str = "16:9",
    variants: int = VARIANTS_PER_SCENE,
    output_dir: Optional[Path] = None,
) -> List[Path]:
    """Generate images for first N scenes via VoiceAPI.

    Args:
        scenes: List from parse_story_to_scenes.
        max_scenes: Only generate for first N scenes.
        aspect_ratio: Image aspect ratio.
        variants: Number of variants per scene.
        output_dir: Where to save PNGs.

    Returns:
        List of saved file paths.
    """
    if not VOICE_API_KEY:
        raise RuntimeError("VOICE_API_KEY not set in .env")

    if output_dir is None:
        output_dir = OUTPUT_DIR

    output_dir.mkdir(parents=True, exist_ok=True)

    scenes_to_gen = scenes[:max_scenes]
    total = len(scenes_to_gen) * variants
    saved_files: List[Path] = []
    generated = 0

    async with httpx.AsyncClient(
        base_url=VOICE_API_BASE_URL.rstrip("/"),
        timeout=httpx.Timeout(180.0, connect=30.0),
        headers={"X-API-Key": VOICE_API_KEY},
    ) as client:
        for scene in scenes_to_gen:
            scene_num = scene["scene"]
            prompt = scene["prompt"]

            print(f"\n🎨 Scene {scene_num:02d} — generating {variants} variants...")

            for v in range(1, variants + 1):
                try:
                    t0 = time.monotonic()
                    resp = await client.post(
                        "/v1/image/create",
                        json={
                            "prompt": prompt,
                            "aspect_ratio": aspect_ratio,
                            "generation_mode": VOICE_API_GENERATION_MODE,
                            "prompt_upsampling": True,
                        },
                    )

                    if resp.status_code != 200:
                        print(f"   ❌ v{v}: API error {resp.status_code}: {resp.text[:150]}")
                        continue

                    data = resp.json()
                    image_b64 = data.get("image_b64", "")
                    if not image_b64:
                        print(f"   ❌ v{v}: Empty image_b64")
                        continue

                    # Save PNG
                    filename = f"scene_{scene_num:02d}_v{v}.png"
                    filepath = output_dir / filename
                    filepath.write_bytes(base64.b64decode(image_b64))
                    saved_files.append(filepath)

                    generated += 1
                    elapsed = time.monotonic() - t0
                    size_kb = filepath.stat().st_size / 1024
                    print(f"   ✅ v{v}: {filename} ({size_kb:.0f} KB, {elapsed:.1f}s) [{generated}/{total}]")

                except Exception as e:
                    print(f"   ❌ v{v}: {type(e).__name__}: {e}")
                    continue

    logger.info(
        "Done! Generated %d/%d images → %s", generated, total, output_dir
    )
    return saved_files


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


async def main() -> None:
    parser = argparse.ArgumentParser(description="Story-to-Images test")
    parser.add_argument(
        "--parse-only",
        action="store_true",
        help="Only parse story to scenes, skip image generation",
    )
    parser.add_argument(
        "--gen-scenes",
        type=int,
        default=DEFAULT_GEN_SCENES,
        help=f"How many first scenes to generate images for (default: {DEFAULT_GEN_SCENES})",
    )
    parser.add_argument(
        "--scenes",
        type=int,
        default=None,
        help="Override target scene count",
    )
    parser.add_argument(
        "--ratio",
        type=str,
        default="16:9",
        help="Aspect ratio for images (default: 16:9)",
    )
    parser.add_argument(
        "--style",
        type=str,
        default="",
        help="Style suffix to append to each prompt (like preset style_suffix)",
    )
    args = parser.parse_args()

    # --- Load story from test.txt ---
    if not STORY_FILE.exists():
        print(f"❌ File not found: {STORY_FILE}")
        print(f"   Create test.txt in project root with your story text.")
        sys.exit(1)

    story_text = STORY_FILE.read_text(encoding="utf-8").strip()
    if len(story_text) < 100:
        print(f"❌ Story too short ({len(story_text)} chars). Put your story in test.txt.")
        sys.exit(1)

    # --- Load user style prompt from story_prompt.txt ---
    if not PROMPT_FILE.exists():
        print(f"❌ File not found: {PROMPT_FILE}")
        print(f"   Create story_prompt.txt in project root.")
        sys.exit(1)

    user_style_prompt = PROMPT_FILE.read_text(encoding="utf-8").strip()

    # --- Info ---
    target = args.scenes or calculate_target_scenes(len(story_text))
    print(f"\n{'='*70}")
    print(f"📖 Story: {len(story_text):,} chars from test.txt")
    print(f"📝 Style prompt: {len(user_style_prompt)} chars from story_prompt.txt")
    print(f"🎬 Target scenes: {target}")
    print(f"🤖 Model: {OPENAI_MODEL}")
    print(f"{'='*70}\n")

    # --- Parse story → scenes ---
    start = time.monotonic()
    scenes = await parse_story_to_scenes(
        story_text,
        user_style_prompt,
        target_scenes=args.scenes,
        style_suffix=args.style,
    )
    parse_time = time.monotonic() - start

    # --- Show ALL prompts in full ---
    print(f"\n{'='*70}")
    print(f"🎬 GPT parsed {len(scenes)} scenes in {parse_time:.1f}s")
    print(f"{'='*70}\n")

    for scene in scenes:
        num = scene["scene"]
        prompt = scene["prompt"]
        print(f"┌─ Scene {num:02d} {'─'*55}")
        print(f"│")
        # Word-wrap prompt for readability
        words = prompt.split()
        line = "│  "
        for word in words:
            if len(line) + len(word) + 1 > 72:
                print(line)
                line = "│  " + word
            else:
                line += (" " + word) if len(line) > 3 else word
        if line.strip("│ "):
            print(line)
        print(f"│")
        print(f"└{'─'*69}\n")

    # --- Save scenes JSON ---
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    scenes_json = OUTPUT_DIR / "scenes.json"
    scenes_json.write_text(
        json.dumps(scenes, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"💾 All {len(scenes)} scenes saved → {scenes_json}\n")

    if args.parse_only:
        print("🛑 --parse-only mode. No images generated.")
        return

    # --- Generate images for first N scenes ---
    gen_count = min(args.gen_scenes, len(scenes))
    total_images = gen_count * VARIANTS_PER_SCENE

    print(f"{'='*70}")
    print(f"🎨 Generating images for first {gen_count} scenes ({total_images} images)")
    print(f"   Ratio: {args.ratio}  |  Variants: {VARIANTS_PER_SCENE}")
    if args.style:
        print(f"   Style: {args.style}")
    print(f"{'='*70}")

    start = time.monotonic()
    saved = await generate_scene_images(
        scenes,
        max_scenes=gen_count,
        aspect_ratio=args.ratio,
        output_dir=OUTPUT_DIR,
    )
    gen_time = time.monotonic() - start

    print(f"\n{'='*70}")
    print(f"✅ Done! {len(saved)}/{total_images} images in {gen_time:.1f}s")
    print(f"📁 Output: {OUTPUT_DIR}")
    print(f"{'='*70}\n")


if __name__ == "__main__":
    asyncio.run(main())
