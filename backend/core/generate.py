"""Recipe generation with RAG: retrieve real recipes, let the LLM adapt them.

1. retrieve_candidates: search ChromaDB (filters are relaxed step by step if
   there are too few hits).
2. The LLM picks the best candidates and adapts them to the user's
   ingredients, diet, portions and time. It must name the candidate it used
   (`basedOnId`), and only real candidate ids pass validation.
3. Fallback: without a usable index, recipes are generated freely (old way).
"""

import json
import logging
from typing import Literal

from pydantic import BaseModel, Field, create_model, model_validator

from core.llm import complete_json
from core.retrieval import IndexNotReadyError, SearchFilters, SearchHit, search_recipes
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

SYSTEM_PROMPT = (
    "You are a professional recipe developer. You always return valid JSON matching "
    "the requested schema and never invent ingredients the user does not have beyond "
    "common pantry staples."
)

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

INSTRUCTION_RULES = [
    "Instructions rules:",
    "- Give 6 to 10 steps. Each step is 1 to 3 full sentences.",
    "- Explain it plainly, the way you would tell a grandparent who is new to cooking:",
    "  say what to do, what it should look, smell or feel like, and roughly how long it takes.",
    "- Use simple everyday words. No chef jargon, no abbreviations.",
    "- Do NOT put the recipe name, cuisine, or serving count inside any step.",
    "- Do NOT number the steps yourself; just write the sentence(s).",
]


# --------------------------------------------------------------------------
# Shared prompt parts
# --------------------------------------------------------------------------


def _format_ingredient(name: str, quantity: float, unit: str) -> str:
    return f"- {name} ({quantity:g}{unit})" if quantity else f"- {name}"


def _diets(req: GenerateRequest) -> list[str]:
    return [d for d in req.dietPreferences if d != "None"]


def _cuisines(req: GenerateRequest) -> list[str]:
    return [c for c in req.cuisines if c != "Any"]


def _request_lines(req: GenerateRequest) -> list[str]:
    diets, cuisines = _diets(req), _cuisines(req)
    return [
        "Available ingredients:",
        "\n".join(_format_ingredient(i.name, i.quantity, i.unit) for i in req.ingredients),
        "",
        f"Portions per recipe: {req.portions}",
        f"Cooking for: {req.people} people",
        f"Target cooking time: {TIME_HINT.get(req.cookingTime, TIME_HINT['medium'])}",
        f"Preferred cuisines: {', '.join(cuisines)}" if cuisines else "Cuisine: chef's choice",
        f"Dietary requirements (must respect all): {', '.join(diets)}" if diets else "Dietary requirements: none",
    ]


# --------------------------------------------------------------------------
# Retrieval
# --------------------------------------------------------------------------


def filter_steps(req: GenerateRequest) -> list[SearchFilters]:
    """Strict filters first, then relaxed: drop cuisine, then time, then diet.
    Diet is dropped last: the LLM can still adapt a recipe to a diet."""
    diets, cuisines, max_minutes = _diets(req), _cuisines(req), TIME_LIMIT.get(req.cookingTime)
    steps = [
        SearchFilters(diets, cuisines, max_minutes),
        SearchFilters(diets, None, max_minutes),
        SearchFilters(diets, None, None),
        SearchFilters(None, None, None),
    ]
    unique: list[SearchFilters] = []
    for f in steps:
        if f.to_where() not in [u.to_where() for u in unique]:
            unique.append(f)
    return unique


def retrieve_candidates(req: GenerateRequest, k: int = CANDIDATE_COUNT) -> list[SearchHit]:
    """Best real recipes for the request; relaxes filters until there are enough."""
    names = [i.name for i in req.ingredients]
    best: list[SearchHit] = []
    for filters in filter_steps(req):
        hits = search_recipes(names, filters, k=k)
        if len(hits) >= MIN_CANDIDATES:
            return hits
        if len(hits) > len(best):
            best = hits
        log.info("Only %d candidates with %s, relaxing filters", len(hits), filters.to_where())
    return best


def format_candidate(hit: SearchHit) -> str:
    r = hit.record
    lines = [
        f"[{r.itemId}] {r.name}",
        f"Cuisine: {r.cuisine} | Type: {r.category or '-'} | Time: {r.cookTimeMinutes} min | "
        f"Serves: {r.servings} | Diet: {', '.join(r.dietTags) or '-'}",
        "Ingredients: " + "; ".join(i.text for i in r.ingredients),
        "Steps: " + " ".join(f"({n}) {s}" for n, s in enumerate(r.instructions, start=1)),
        f"User already has: {', '.join(hit.matched) or '-'} | Missing: {', '.join(hit.missing) or '-'}",
    ]
    return "\n".join(lines)


# --------------------------------------------------------------------------
# RAG generation
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


def build_rag_prompt(req: GenerateRequest, hits: list[SearchHit], count: int) -> str:
    example = {**EXAMPLE_RECIPE, "portions": req.portions, "basedOnId": hits[0].record.itemId}
    candidates = "\n\n".join(format_candidate(h) for h in hits)
    return "\n".join([
        f"Below are {len(hits)} real recipes from our recipe database (candidates).",
        f"Pick the {count} best candidates for this user, all different dishes, and adapt each one.",
        "",
        *_request_lines(req),
        "",
        "How to pick:",
        "- Prefer candidates that use many of the user's ingredients and are real meals or dishes.",
        "- Avoid basics like stocks, plain sauces, pickles or drinks unless nothing else fits.",
        "",
        "How to adapt:",
        "- Keep the character of the original dish, but cook it with the user's ingredients.",
        "- Main ingredients must come from the user's list or common pantry staples",
        "  (salt, pepper, oil, water, basic spices). Replace or leave out what the user does not have.",
        "- Respect every dietary requirement strictly; replace ingredients that break it.",
        "- Scale amounts to the requested portions and aim for the target cooking time.",
        "- You may rename the dish to reflect your changes.",
        "- dietTags: only tags that the adapted recipe really satisfies.",
        "- nutrition: your best estimate per portion (grams, calories in kcal).",
        "- basedOnId: the id in [brackets] of the candidate you adapted.",
        "",
        "Candidates:",
        candidates,
        "",
        'Respond with ONLY a JSON object, no markdown: {"recipes": [recipe, ...]}.',
        "Each recipe looks exactly like this example (shortened to 2 steps here):",
        json.dumps(example, indent=2),
        "",
        *INSTRUCTION_RULES,
    ])


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


# --------------------------------------------------------------------------
# Free generation (fallback, the original behaviour)
# --------------------------------------------------------------------------


def build_prompt(req: GenerateRequest) -> str:
    example = {**EXAMPLE_RECIPE, "portions": req.portions}
    return "\n".join([
        f"Create exactly {RECIPE_COUNT} distinct recipes that primarily use the ingredients below.",
        "Common pantry staples (salt, pepper, oil, water, basic spices) may be assumed.",
        "",
        *_request_lines(req),
        "",
        'Respond with ONLY a JSON object, no markdown: {"recipes": [recipe, recipe, recipe]}.',
        "Each recipe looks exactly like this example (shortened to 2 steps here):",
        json.dumps(example, indent=2),
        "Nutrition values are per portion, in grams except calories (kcal).",
        "",
        *INSTRUCTION_RULES,
    ])


def to_response(drafts: RecipeDrafts, portions: int) -> RecipesResponse:
    """Add ids (1..n), enforce the requested portions, cut to RECIPE_COUNT."""
    recipes = [
        Recipe(**d.model_dump(exclude={"portions"}), id=i, portions=portions)
        for i, d in enumerate(drafts.recipes[:RECIPE_COUNT], start=1)
    ]
    return RecipesResponse(recipes=recipes)


async def generate_free(req: GenerateRequest) -> RecipesResponse:
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": build_prompt(req)},
    ]
    drafts = await complete_json(messages, RecipeDrafts)
    return to_response(drafts, req.portions)


# --------------------------------------------------------------------------
# Entry point
# --------------------------------------------------------------------------


async def generate_recipes(req: GenerateRequest) -> RecipesResponse:
    try:
        hits = retrieve_candidates(req)
    except IndexNotReadyError as err:
        log.warning("Recipe index not ready, falling back to free generation: %s", err)
        return await generate_free(req)
    if not hits:
        log.warning("No candidates found, falling back to free generation")
        return await generate_free(req)

    count = min(RECIPE_COUNT, len(hits))
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": build_rag_prompt(req, hits, count)},
    ]
    schema = adapted_schema([h.record.itemId for h in hits])
    adapted = await complete_json(messages, schema)
    log.info("Generated %d recipes based on %s", len(adapted.recipes), [r.basedOnId for r in adapted.recipes])
    return to_rag_response(adapted, hits, req.portions)
