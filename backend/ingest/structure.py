"""LLM step of the ingest: raw recipe text -> validated RecipeRecord."""

import json

from core.config import get_settings
from core.llm import complete_json
from core.schemas import CUISINE_VALUES, DIET_VALUES, RecipeExtraction, RecipeRecord, RecipeSource
from ingest.wikibooks import SOURCE_LICENSE, SOURCE_NAME, category_name, make_item_id, to_source_text

SYSTEM_PROMPT = (
    "You are a careful recipe data editor. You convert recipe web pages into clean JSON. "
    "You only use information that is in the text. You never invent ingredients, steps or amounts."
)

EXAMPLE_INPUT = """Title: Simple Tomato Soup
Category: Soup
Servings: 4
Time: 40 minutes

## Ingredients
- 1 ½ lb (700 g) ripe tomatoes, chopped
- 1 onion, diced
- 2 tablespoons butter
- Salt to taste
- Fresh basil (optional)

## Procedure
- Melt the butter in a pot and fry the onion until soft, about 5 minutes.
- Add the tomatoes and simmer for 25 minutes. Blend until smooth and season with salt."""

EXAMPLE_OUTPUT = {
    "name": "Simple Tomato Soup",
    "description": "A smooth, comforting soup of ripe tomatoes and onion simmered in butter.",
    "cuisine": "Other",
    "dietTags": ["Vegetarian", "Gluten-Free"],
    "cookTimeMinutes": 40,
    "servings": 4,
    "ingredients": [
        {"text": "1 ½ lb (700 g) ripe tomatoes, chopped", "name": "tomato", "quantity": 700, "unit": "g", "optional": False},
        {"text": "1 onion, diced", "name": "onion", "quantity": 1, "unit": "pcs", "optional": False},
        {"text": "2 tablespoons butter", "name": "butter", "quantity": 2, "unit": "tbsp", "optional": False},
        {"text": "Salt to taste", "name": "salt", "quantity": None, "unit": None, "optional": False},
        {"text": "Fresh basil (optional)", "name": "basil", "quantity": None, "unit": None, "optional": True},
    ],
    "instructions": [
        "Melt the butter in a pot and fry the onion until soft, about 5 minutes.",
        "Add the tomatoes and simmer for 25 minutes.",
        "Blend until smooth and season with salt.",
    ],
}

RULES = f"""Rules:
- name: the recipe title, cleaned up (no "Cookbook:" prefix).
- description: 1-2 appetising sentences based only on the text.
- cuisine: exactly one of {list(CUISINE_VALUES)}. Use "Other" if none fits clearly.
- dietTags: only tags from {list(DIET_VALUES)} that ALL non-optional ingredients satisfy.
  Be strict: honey is not Vegan, butter/cheese/milk are not Dairy-Free, flour/bread/pasta/soy sauce are not Gluten-Free.
  If unsure, leave the tag out. An empty list is fine.
- cookTimeMinutes: total time in minutes from the "Time" field; if missing, estimate from the steps.
  Long waiting times (e.g. "overnight") count.
- servings: from the "Servings" field; if missing or a range, pick a sensible integer.
- ingredients: one entry per ingredient line, in order. Skip lines that are not ingredients (headings, notes).
  text = the original line unchanged. name = the core ingredient, lowercase, singular, English, no brand
  or preparation ("chopped red onions" -> "red onion"). quantity = a number (fractions as decimals) or null.
  unit = a short unit like g, kg, ml, l, tsp, tbsp, cup, oz, lb, pcs, pinch, clove, or null.
  Prefer metric if the line gives both. optional = true only if the text says optional / to serve / garnish.
- instructions: the procedure steps in order, close to the original wording. Split very long steps,
  merge tiny fragments, drop numbering. Do not add steps that are not in the text.
- Return ONLY the JSON object, no markdown."""


def build_messages(source_text: str) -> list[dict]:
    return [
        {"role": "system", "content": SYSTEM_PROMPT},
        {
            "role": "user",
            "content": "\n\n".join([
                "Convert this recipe page into JSON.",
                RULES,
                f"Example input:\n{EXAMPLE_INPUT}",
                f"Example output:\n{json.dumps(EXAMPLE_OUTPUT, ensure_ascii=False)}",
                f"Now convert this recipe page:\n{source_text}",
            ]),
        },
    ]


async def structure_recipe(raw: dict) -> RecipeRecord:
    """Raw Wikibooks recipe -> validated record (LLM + validation + auto-repair)."""
    s = get_settings()
    extraction = await complete_json(
        build_messages(to_source_text(raw)),
        RecipeExtraction,
        temperature=0,
        model=s.ingest_model or s.llm_model,
    )
    return RecipeRecord(
        **extraction.model_dump(),
        itemId=make_item_id(raw["url"]),
        category=category_name(raw),
        source=RecipeSource(name=SOURCE_NAME, url=raw["url"], license=SOURCE_LICENSE),
    )
