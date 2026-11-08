"""Fridge photo -> ingredient list (vision LLM).

- The image is checked by its real content (magic bytes), not by the file name
  or the Content-Type the browser sends.
- It is only kept in memory for the one LLM call: never written to disk,
  never logged.
- The prompt says: describe only what you can see, do not invent anything.
- The answer is validated against `DetectedIngredients` (with auto-repair),
  in the same format as Step 1 of the app (name, quantity, unit).
"""

import base64
import logging
import re

from core.agents.config import build_messages
from core.config import get_settings
from core.llm import complete_json
from core.schemas import DetectedIngredients

log = logging.getLogger(__name__)

MAX_IMAGE_BYTES = 4 * 1024 * 1024  # the frontend resizes to ~0.3 MB; this is a hard cap
MIN_IMAGE_BYTES = 100


class InvalidImageError(ValueError):
    """Not a supported image (or empty / too large)."""


def detect_image_type(data: bytes) -> str:
    """Return the MIME type from the file's first bytes. Raises InvalidImageError."""
    if len(data) < MIN_IMAGE_BYTES:
        raise InvalidImageError("The image is empty or broken.")
    if len(data) > MAX_IMAGE_BYTES:
        raise InvalidImageError(f"The image is too large (max {MAX_IMAGE_BYTES // (1024 * 1024)} MB).")
    if data.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    raise InvalidImageError("Please upload a JPEG, PNG or WebP photo.")


def build_vision_messages(data: bytes, mime: str) -> list[dict]:
    """Task prompt from the agent config + the image as a data URL (multimodal message)."""
    messages = build_messages("detect_ingredients", "The photo is attached.")
    data_url = f"data:{mime};base64,{base64.b64encode(data).decode('ascii')}"
    messages[-1]["content"] = [
        {"type": "text", "text": messages[-1]["content"]},
        {"type": "image_url", "image_url": {"url": data_url}},
    ]
    return messages


# Generic words for packaging or unknown food: useless as a recipe ingredient.
_NOT_AN_INGREDIENT = re.compile(
    r"^(food|foods|leftovers?|groceries|snacks?|drinks?|beverages?|condiments?|sauces?|"
    r"(food |plastic |glass )?(containers?|bottles?|jars?|boxe?s?|packages?|packs?|cans?|bags?|tubs?|cartons?|tupperware)|"
    r"canned (food|goods)|unknown.*|.*\bitems?)$",
    re.IGNORECASE,
)


def drop_generic_items(result: DetectedIngredients) -> DetectedIngredients:
    """Remove entries like 'food container' or 'bottle' that slipped through the prompt."""
    kept = [i for i in result.ingredients if not _NOT_AN_INGREDIENT.match(i.name.strip())]
    return result.model_copy(update={"ingredients": kept})


async def detect_ingredients(data: bytes) -> DetectedIngredients:
    """Recognize visible food in a photo. The image bytes are not stored anywhere."""
    mime = detect_image_type(data)
    s = get_settings()
    result = await complete_json(
        build_vision_messages(data, mime),
        DetectedIngredients,
        temperature=0,
        model=s.vision_model or s.llm_model,
    )
    result = drop_generic_items(result)
    log.info("Photo (%s, %d KB): %d ingredients detected", mime, len(data) // 1024, len(result.ingredients))
    return result
