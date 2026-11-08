"""MCP server: Code a Cuisine's recipe search and USDA nutrition as tools for AI assistants.

Tools (no LLM inside, no API keys needed; same `core` code as the web API):
- search_recipes  find real recipes by ingredients, with diet / cuisine / time filters
- get_recipe      full recipe (ingredients, steps, source) by id
- get_nutrition   calories and macros from USDA FoodData Central, calculated in code

Resources (read-only):
- recipes://cuisines   cuisines in the database with recipe counts
- recipes://diets      supported diets and their exact definitions

Run locally over stdio (e.g. for Claude Desktop / Claude Code), from the backend/ folder:
    uv run python -m mcp_server.server
"""

import asyncio
import json
import os
from collections import Counter

os.environ.setdefault("ANONYMIZED_TELEMETRY", "False")  # keep ChromaDB quiet on stdout

from pydantic import BaseModel, Field  # noqa: E402

from core.agents.config import DIET_DEFINITIONS  # noqa: E402
from core.nutrition import SOURCE as NUTRITION_SOURCE  # noqa: E402
from core.nutrition import calculate, match_foods  # noqa: E402
from core.recipes import get_record, records_by_id  # noqa: E402
from core.retrieval import IndexNotReadyError, SearchFilters  # noqa: E402
from core.retrieval import search_recipes as _search  # noqa: E402
from core.schemas import (  # noqa: E402
    CUISINE_VALUES,
    DIET_VALUES,
    MAX_INGREDIENTS,
    IngredientWeight,
    Nutrition,
    RecipeSource,
)
from mcp.server.mcpserver import MCPServer  # noqa: E402
from mcp.server.mcpserver.exceptions import ToolError  # noqa: E402

MAX_RESULTS = 10
MAX_NUTRITION_ITEMS = 40


# --------------------------------------------------------------------------
# Typed tool outputs (clients get an output schema)
# --------------------------------------------------------------------------


class RecipeHit(BaseModel):
    itemId: str
    name: str
    cuisine: str
    category: str | None
    cookTimeMinutes: int
    dietTags: list[str]
    score: float = Field(description="0..1, similarity combined with ingredient match")
    uses: list[str] = Field(description="Recipe ingredients the user has")
    missing: list[str] = Field(description="Main recipe ingredients the user does not have")
    url: str


class SearchResult(BaseModel):
    count: int
    results: list[RecipeHit]
    hint: str | None = None


class RecipeDetail(BaseModel):
    itemId: str
    name: str
    description: str
    cuisine: str
    category: str | None
    dietTags: list[str]
    cookTimeMinutes: int
    servings: int
    ingredients: list[str]
    instructions: list[str]
    source: RecipeSource


class NutritionItem(BaseModel):
    food: str
    grams: float
    usdaMatch: str | None = Field(description="USDA food the item was matched to (None = not found)")
    fdcId: int | None


class NutritionResultOut(BaseModel):
    perPortion: Nutrition
    portions: int
    totalGrams: float
    coverage: float = Field(description="Share of the weight that was matched to USDA foods")
    reliable: bool = Field(description="True if at least 80% of the weight was matched")
    items: list[NutritionItem]
    source: str

mcp = MCPServer(
    name="code-a-cuisine",
    title="Code a Cuisine",
    version="1.0.0",
    website_url="https://code-a-cuisine-three.vercel.app",
    instructions=(
        "Recipe search over ~750 real recipes (Wikibooks Cookbook, CC BY-SA 4.0) and nutrition "
        "values from USDA FoodData Central.\n"
        "- Use search_recipes when the user wants ideas for what to cook with certain ingredients, "
        "optionally for a diet, cuisine or time limit.\n"
        "- Use get_recipe when you need the full ingredients and steps of a recipe from the search.\n"
        "- Use get_nutrition when the user asks for calories or macros of foods or a dish; pass each "
        "food with its weight in grams.\n"
        "Never invent recipes or nutrition numbers; always use the tools for data. "
        "When you show a recipe, mention its source link (license CC BY-SA 4.0)."
    ),
)


# --------------------------------------------------------------------------
# Tools
# --------------------------------------------------------------------------


@mcp.tool(
    title="Search recipes",
    description=(
        "Find real recipes for the given ingredients. Returns the best matches with a score, "
        "which of the user's ingredients each recipe uses and which ingredients are missing."
    ),
)
async def search_recipes(
    ingredients: list[str] = Field(description="Ingredients the user has, in English, e.g. ['chicken', 'rice']", min_length=1, max_length=MAX_INGREDIENTS),
    diets: list[str] = Field(default_factory=list, description=f"Recipes must satisfy ALL of these. Allowed: {', '.join(DIET_VALUES)}"),
    cuisines: list[str] = Field(default_factory=list, description=f"Recipe must be ONE of these. Allowed: {', '.join(CUISINE_VALUES)}"),
    max_minutes: int | None = Field(default=None, ge=1, le=2880, description="Maximum total time in minutes"),
    limit: int = Field(default=5, ge=1, le=MAX_RESULTS, description="Number of results"),
) -> SearchResult:
    filters = SearchFilters(diets=diets or None, cuisines=cuisines or None, max_minutes=max_minutes)
    try:
        hits = await asyncio.to_thread(_search, ingredients, filters, limit)
    except (ValueError, IndexNotReadyError) as err:  # bad filter value / index missing: tell the AI why
        raise ToolError(str(err)) from err
    results = [
        RecipeHit(
            itemId=h.record.itemId,
            name=h.record.name,
            cuisine=h.record.cuisine,
            category=h.record.category,
            cookTimeMinutes=h.record.cookTimeMinutes,
            dietTags=h.record.dietTags,
            score=round(h.score, 3),
            uses=h.matched,
            missing=h.missing,
            url=h.record.source.url,
        )
        for h in hits
    ]
    hint = None if results else "No recipe matches these filters. Try fewer filters or a longer time limit."
    return SearchResult(count=len(results), results=results, hint=hint)


@mcp.tool(
    title="Get recipe",
    description="Full recipe by its itemId (from search_recipes): ingredients, steps, time, servings and source.",
)
async def get_recipe(item_id: str = Field(description="Recipe id, e.g. 'wb-1a2b3c4d5e6f'", min_length=1, max_length=40)) -> RecipeDetail:
    record = get_record(item_id.strip())
    if record is None:
        raise ToolError(f"No recipe with itemId '{item_id}'. Use search_recipes to find valid ids.")
    return RecipeDetail(
        **record.model_dump(exclude={"ingredients"}),
        ingredients=[i.text for i in record.ingredients],
    )


@mcp.tool(
    title="Get nutrition",
    description=(
        "Calories, protein, carbs and fat per portion, calculated from USDA FoodData Central "
        "(per-100 g values x grams). Shows which USDA food each item was matched to."
    ),
)
async def get_nutrition(
    items: list[IngredientWeight] = Field(
        description="Foods with their weight in grams for the whole dish, e.g. [{'food': 'rice', 'grams': 200}]",
        min_length=1,
        max_length=MAX_NUTRITION_ITEMS,
    ),
    portions: int = Field(default=1, ge=1, le=100, description="Number of portions the dish is split into"),
) -> NutritionResultOut:
    pairs = [(i.food, i.grams) for i in items]
    try:
        result = await asyncio.to_thread(calculate, pairs, portions)
        matches = await asyncio.to_thread(match_foods, [food for food, _ in pairs])
    except IndexNotReadyError as err:
        raise ToolError(str(err)) from err
    return NutritionResultOut(
        perPortion=result.nutrition,
        portions=portions,
        totalGrams=round(result.total_grams, 1),
        coverage=round(result.coverage, 3),
        reliable=result.reliable,
        items=[
            NutritionItem(food=food, grams=grams, usdaMatch=m.food.description if m else None, fdcId=m.food.fdcId if m else None)
            for (food, grams), m in zip(pairs, matches)
        ],
        source=NUTRITION_SOURCE,
    )


# --------------------------------------------------------------------------
# Resources
# --------------------------------------------------------------------------


@mcp.resource("recipes://cuisines", name="cuisines", title="Cuisines", mime_type="application/json",
              description="Cuisines in the recipe database with the number of recipes for each.")
def cuisines_resource() -> str:
    counts = Counter(r.cuisine for r in records_by_id().values())
    return json.dumps({"cuisines": {c: counts.get(c, 0) for c in CUISINE_VALUES}, "total": sum(counts.values())})


@mcp.resource("recipes://diets", name="diets", title="Diets", mime_type="application/json",
              description="Supported diet filters and the exact rule used for each.")
def diets_resource() -> str:
    return json.dumps({"diets": DIET_DEFINITIONS})


if __name__ == "__main__":
    mcp.run("stdio")
