"""Pydantic models shared by the whole backend.

Defined once here and reused everywhere (API, LLM validation, ingest, MCP).

- Request side: `GenerateRequest` cleans and limits user input the same way
  `lib/validate.js` does (lenient: bad values fall back to defaults).
- Response side: `Recipe` matches what `api/generate.js` returns today, so the
  frontend (RecipeCard, ResultsPage, Recipe Book) keeps working unchanged.
  New optional fields may be added later; existing ones must not change.
"""

import math
import re
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator

# --------------------------------------------------------------------------
# Allowed values and limits (keep in sync with the frontend)
# --------------------------------------------------------------------------

MAX_BODY_BYTES = 10 * 1024
MAX_INGREDIENTS = 20
INGREDIENT_NAME_MAX = 50
MAX_QUANTITY = 100_000
MAX_PORTIONS = 20
MAX_PEOPLE = 20

UNITS = ("g", "ml", "oz", "pcs", "tsp", "tbsp", "cup")
COOKING_TIMES = ("quick", "medium", "complex")
CUISINES = (
    "Any", "German", "Italian", "Indian", "Japanese", "Mexican",
    "French", "Thai", "American", "Mediterranean", "Other",
)
DIETS = (
    "None", "Vegan", "Vegetarian", "Keto",
    "Gluten-Free", "Dairy-Free", "Low-Carb", "Paleo",
)

# Control characters could smuggle extra lines/instructions into the prompt.
_CONTROL_CHARS = re.compile(r"[\x00-\x1f\x7f]+")


def clean_text(value: Any, max_len: int) -> str:
    text = "" if value is None else str(value)
    text = _CONTROL_CHARS.sub(" ", text)
    return " ".join(text.split())[:max_len]


def to_number(value: Any) -> float | None:
    try:
        n = float(value)
    except (TypeError, ValueError):
        return None
    return n if math.isfinite(n) else None


def clamp_int(value: Any, low: int, high: int, fallback: int) -> int:
    n = to_number(value)
    if n is None:
        return fallback
    return min(high, max(low, math.floor(n + 0.5)))


def pick_from_list(values: Any, allowed: tuple[str, ...]) -> list[str]:
    """Keep only allowed values, without duplicates, in input order."""
    if not isinstance(values, list):
        return []
    out: list[str] = []
    for v in values:
        s = str(v)
        if s in allowed and s not in out:
            out.append(s)
    return out


# --------------------------------------------------------------------------
# Request
# --------------------------------------------------------------------------


class Ingredient(BaseModel):
    name: str
    quantity: float = 0
    unit: str = "g"


class GenerateRequest(BaseModel):
    """Cleaned body of POST /generate. Invalid optional values fall back to defaults."""

    ingredients: list[Ingredient]
    portions: int = 2
    people: int = 2
    cookingTime: str = "medium"
    cuisines: list[str] = Field(default_factory=list)
    dietPreferences: list[str] = Field(default_factory=list)

    @field_validator("ingredients", mode="before")
    @classmethod
    def _clean_ingredients(cls, value: Any) -> list[dict]:
        items = value if isinstance(value, list) else []
        if len(items) > MAX_INGREDIENTS:
            raise ValueError(f"Too many ingredients (max {MAX_INGREDIENTS}).")

        cleaned = []
        for item in items:
            if not isinstance(item, dict):
                continue
            name = clean_text(item.get("name"), INGREDIENT_NAME_MAX)
            if not name:
                continue
            quantity = to_number(item.get("quantity"))
            quantity = min(quantity, MAX_QUANTITY) if quantity and quantity > 0 else 0
            unit = str(item.get("unit"))
            cleaned.append({"name": name, "quantity": quantity, "unit": unit if unit in UNITS else UNITS[0]})

        if not cleaned:
            raise ValueError("Add at least one ingredient.")
        return cleaned

    @field_validator("portions", mode="before")
    @classmethod
    def _clamp_portions(cls, value: Any) -> int:
        return clamp_int(value, 1, MAX_PORTIONS, 2)

    @field_validator("people", mode="before")
    @classmethod
    def _clamp_people(cls, value: Any) -> int:
        return clamp_int(value, 1, MAX_PEOPLE, 2)

    @field_validator("cookingTime", mode="before")
    @classmethod
    def _check_time(cls, value: Any) -> str:
        return str(value) if str(value) in COOKING_TIMES else "medium"

    @field_validator("cuisines", mode="before")
    @classmethod
    def _pick_cuisines(cls, value: Any) -> list[str]:
        return pick_from_list(value, CUISINES)

    @field_validator("dietPreferences", mode="before")
    @classmethod
    def _pick_diets(cls, value: Any) -> list[str]:
        return pick_from_list(value, DIETS)


# --------------------------------------------------------------------------
# Recipes
# --------------------------------------------------------------------------


class Nutrition(BaseModel):
    """Nutrition per portion. Calories in kcal, the rest in grams."""

    calories: float = Field(default=0, ge=0)
    protein: float = Field(default=0, ge=0)
    carbs: float = Field(default=0, ge=0)
    fat: float = Field(default=0, ge=0)


class RecipeDraft(BaseModel):
    """A recipe without an id. This is what the LLM must return."""

    name: str = Field(min_length=1)
    description: str = ""
    cookTime: str = "30 min"
    cuisine: str = "Various"
    dietTags: list[str] = Field(default_factory=list)
    portions: int = Field(default=2, ge=1)
    nutrition: Nutrition = Field(default_factory=Nutrition)
    ingredients: list[str] = Field(min_length=1)
    instructions: list[str] = Field(min_length=1)


class RecipeDrafts(BaseModel):
    """LLM output for recipe generation: `{"recipes": [...]}`."""

    recipes: list[RecipeDraft] = Field(min_length=1)


class Recipe(RecipeDraft):
    """One recipe as the frontend expects it."""

    id: int


class RecipesResponse(BaseModel):
    """Response body of the generate endpoint: `{"recipes": [...]}`."""

    recipes: list[Recipe]


# --------------------------------------------------------------------------
# Recipe database records (ingest -> recipes.jsonl -> ChromaDB)
# --------------------------------------------------------------------------

# Filter values for retrieval. Same lists as the frontend, without "Any"/"None",
# so every stored value is one the user can actually pick.
CUISINE_VALUES = tuple(c for c in CUISINES if c != "Any")
DIET_VALUES = tuple(d for d in DIETS if d != "None")
CuisineName = Literal[*CUISINE_VALUES]
DietName = Literal[*DIET_VALUES]


class RecipeIngredient(BaseModel):
    """One ingredient line, original text plus a normalized name for search."""

    text: str = Field(min_length=1, description="Original ingredient line, unchanged")
    name: str = Field(min_length=1, max_length=60, description="Core ingredient, lowercase, singular, English")
    quantity: float | None = Field(default=None, ge=0)
    unit: str | None = Field(default=None, max_length=20)
    optional: bool = False


class RecipeExtraction(BaseModel):
    """What the LLM extracts from a raw recipe text. Everything else is set in code."""

    name: str = Field(min_length=1, max_length=120)
    description: str = Field(min_length=1, max_length=400)
    cuisine: CuisineName
    dietTags: list[DietName] = Field(default_factory=list)
    cookTimeMinutes: int = Field(ge=1, le=2880)
    servings: int = Field(ge=1, le=100)
    ingredients: list[RecipeIngredient] = Field(min_length=1)
    instructions: list[str] = Field(min_length=1)

    @field_validator("dietTags")
    @classmethod
    def _unique_tags(cls, tags: list[str]) -> list[str]:
        return list(dict.fromkeys(tags))

    @field_validator("instructions")
    @classmethod
    def _no_empty_steps(cls, steps: list[str]) -> list[str]:
        steps = [s.strip() for s in steps if s and s.strip()]
        if not steps:
            raise ValueError("instructions must contain at least one non-empty step")
        return steps


class RecipeSource(BaseModel):
    name: str
    url: str
    license: str


class RecipeRecord(RecipeExtraction):
    """One recipe in our database. `itemId` is unique and stable across re-runs."""

    itemId: str
    category: str | None = None
    source: RecipeSource
