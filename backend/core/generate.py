"""Building blocks for recipe generation, used by the agent workflow
(core/agents/graph.py): prompt context, retrieval with relaxed filters,
output schemas and conversion to the frontend format.
"""

import json
import logging
import re
from typing import Literal

from pydantic import BaseModel, Field, create_model, model_validator

from core import diet_rules
from core.retrieval import SearchFilters, SearchHit, search_recipes
from core.schemas import BasedOn, GenerateRequest, Recipe, RecipeDraft, RecipeDrafts, RecipesResponse

log = logging.getLogger(__name__)

RECIPE_COUNT = 3
CANDIDATE_COUNT = 6
MIN_CANDIDATES = RECIPE_COUNT

TIME_HINT = {
    "quick": "about 15 minutes",
    "medium": "about 30 minutes",
    "complex": "60 minutes or more",
}
# Hard upper limit for the retrieval filter (a bit of slack over the hint).
TIME_LIMIT = {"quick": 25, "medium": 50, "complex": None}

# One-shot example: shows the exact shape and the style of the instructions.
EXAMPLE_RECIPE = {
    "name": "Garlic Tomato Spaghetti",
    "description": "A quick, fresh pasta with soft tomatoes and plenty of garlic.",
    "cookTime": "25 min",
    "cuisine": "Italian",
    "dietTags": ["Vegetarian"],
    "portions": 2,
    "nutrition": {"calories": 520, "protein": 16, "carbs": 82, "fat": 14},
    "ingredients": ["200 g spaghetti", "3 tomatoes, chopped", "2 cloves garlic, sliced", "2 tbsp olive oil"],
    "instructions": [
        "Bring a big pot of salted water to the boil and cook the spaghetti for about 9 minutes, until soft but still a little firm.",
        "Meanwhile, warm the olive oil in a pan over medium heat and add the garlic. Stir for about 1 minute until it smells nice but is not brown.",
    ],
}


# --------------------------------------------------------------------------
# Request context
# --------------------------------------------------------------------------


def _format_ingredient(name: str, quantity: float, unit: str) -> str:
    return f"- {name} ({quantity:g}{unit})" if quantity else f"- {name}"


def diets(req: GenerateRequest) -> list[str]:
    return [d for d in req.dietPreferences if d != "None"]


def cuisines(req: GenerateRequest) -> list[str]:
    return [c for c in req.cuisines if c != "Any"]


def request_context(req: GenerateRequest) -> str:
    d, c = diets(req), cuisines(req)
    return "\n".join([
        "Available ingredients:",
        "\n".join(_format_ingredient(i.name, i.quantity, i.unit) for i in req.ingredients),
        "",
        f"Portions per recipe: {req.portions}",
        f"Cooking for: {req.people} people",
        f"Target cooking time: {TIME_HINT.get(req.cookingTime, TIME_HINT['medium'])}",
        f"Preferred cuisines: {', '.join(c)}" if c else "Cuisine: chef's choice",
        f"Dietary requirements (must respect all): {', '.join(d)}" if d else "Dietary requirements: none",
        *_conflict_lines(req, d),
    ])


def _conflict_lines(req: GenerateRequest, required: list[str]) -> list[str]:
    """Tell the chef up front which of the user's ingredients break the diet."""
    found = diet_rules.conflicts([i.name for i in req.ingredients], required)
    if not found:
        return []
    return ["", "MUST NOT USE (these ingredients of the user break the required diet):", *(f"- {c}" for c in found)]


def example_json(portions: int, based_on_id: str | None = None) -> str:
    example = {**EXAMPLE_RECIPE, "portions": portions}
    if based_on_id:
        example["basedOnId"] = based_on_id
    return json.dumps(example, indent=2)


# --------------------------------------------------------------------------
# Retrieval
# --------------------------------------------------------------------------


def filter_steps(req: GenerateRequest) -> list[SearchFilters]:
    """Strict filters first, then relaxed: drop cuisine, then time, then diet.
    Diet is dropped last: the chef can still adapt a recipe to a diet."""
    d, c, max_minutes = diets(req), cuisines(req), TIME_LIMIT.get(req.cookingTime)
    steps = [
        SearchFilters(d, c, max_minutes),
        SearchFilters(d, None, max_minutes),
        SearchFilters(d, None, None),
        SearchFilters(None, None, None),
    ]
    unique: list[SearchFilters] = []
    for f in steps:
        if f.to_where() not in [u.to_where() for u in unique]:
            unique.append(f)
    return unique


# Basics (sauces, stocks, drinks ...) are poor templates for a meal.
_BASIC = re.compile(
    r"\b(sauce|dressing|mayonnaise|dip|stock|broth|marinade|condiment|chutney|salsa|pickle|pickled|"
    r"frosting|icing|syrup|jam|jelly|beverage|drink|seasoning|spice mix)\b",
    re.IGNORECASE,
)


def is_basic(hit: SearchHit) -> bool:
    return bool(_BASIC.search(hit.record.category or "") or _BASIC.search(hit.record.name))


def prefer_dishes(hits: list[SearchHit], k: int) -> list[SearchHit]:
    """Real dishes first; basics only fill up if there are too few dishes."""
    dishes = [h for h in hits if not is_basic(h)]
    if len(dishes) >= MIN_CANDIDATES:
        return dishes[:k]
    return (dishes + [h for h in hits if is_basic(h)])[:k]


def retrieve_candidates(req: GenerateRequest, terms: list[str] | None = None, k: int = CANDIDATE_COUNT) -> list[SearchHit]:
    """Best real recipes for the request; relaxes filters until there are enough dishes."""
    names = terms or [i.name for i in req.ingredients]
    best: list[SearchHit] = []
    for filters in filter_steps(req):
        hits = prefer_dishes(search_recipes(names, filters, k=k * 2), k)
        if len([h for h in hits if not is_basic(h)]) >= MIN_CANDIDATES:
            return hits
        if len(hits) > len(best):
            best = hits
        log.info("Only %d dish candidates with %s, relaxing filters", len(hits), filters.to_where())
    return best


def format_candidate(hit: SearchHit) -> str:
    r = hit.record
    return "\n".join([
        f"[{r.itemId}] {r.name}",
        f"Cuisine: {r.cuisine} | Type: {r.category or '-'} | Time: {r.cookTimeMinutes} min | "
        f"Serves: {r.servings} | Diet: {', '.join(r.dietTags) or '-'}",
        "Ingredients: " + "; ".join(i.text for i in r.ingredients),
        "Steps: " + " ".join(f"({n}) {s}" for n, s in enumerate(r.instructions, start=1)),
        f"User already has: {', '.join(hit.matched) or '-'} | Missing: {', '.join(hit.missing) or '-'}",
    ])


def candidates_context(hits: list[SearchHit]) -> str:
    return "Candidates (real recipes from our database):\n\n" + "\n\n".join(format_candidate(h) for h in hits)


# --------------------------------------------------------------------------
# Output schemas and conversion
# --------------------------------------------------------------------------


class _AdaptedRecipesBase(BaseModel):
    @model_validator(mode="after")
    def _one_recipe_per_candidate(self):
        ids = [r.basedOnId for r in self.recipes]
        if len(ids) != len(set(ids)):
            raise ValueError("Every recipe must be based on a different candidate: basedOnId values must be unique.")
        return self


def adapted_schema(candidate_ids: list[str]):
    """Output schema: `basedOnId` only accepts real candidate ids, each one at most once."""
    adapted = create_model(
        "AdaptedRecipe",
        __base__=RecipeDraft,
        basedOnId=(Literal[tuple(candidate_ids)], Field(description="id of the candidate recipe used")),
    )
    return create_model("AdaptedRecipes", __base__=_AdaptedRecipesBase, recipes=(list[adapted], Field(min_length=1)))


def to_rag_response(adapted, hits: list[SearchHit], portions: int) -> RecipesResponse:
    """Add ids, real source info (from our database, not from the LLM) and portions."""
    by_id = {h.record.itemId: h.record for h in hits}
    recipes = []
    for i, item in enumerate(adapted.recipes[:RECIPE_COUNT], start=1):
        source = by_id[item.basedOnId]
        recipes.append(Recipe(
            **item.model_dump(exclude={"portions", "basedOnId"}),
            id=i,
            portions=portions,
            basedOn=BasedOn(
                itemId=source.itemId,
                name=source.name,
                url=source.source.url,
                source=source.source.name,
                license=source.source.license,
            ),
        ))
    return RecipesResponse(recipes=recipes)


def to_response(drafts: RecipeDrafts, portions: int) -> RecipesResponse:
    """Free generation: add ids (1..n), enforce the requested portions, cut to RECIPE_COUNT."""
    recipes = [
        Recipe(**d.model_dump(exclude={"portions"}), id=i, portions=portions)
        for i, d in enumerate(drafts.recipes[:RECIPE_COUNT], start=1)
    ]
    return RecipesResponse(recipes=recipes)
