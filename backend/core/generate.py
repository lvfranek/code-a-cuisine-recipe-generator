"""Recipe generation: prompt building + LLM call + conversion to the frontend format.

Ported from api/generate.js. In Phase 1 this will use real recipes from ChromaDB.
"""

import json

from core.llm import complete_json
from core.schemas import GenerateRequest, Recipe, RecipeDrafts, RecipesResponse

RECIPE_COUNT = 3

TIME_HINT = {
    "quick": "about 15 minutes",
    "medium": "about 30 minutes",
    "complex": "60 minutes or more",
}

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


def _format_ingredient(name: str, quantity: float, unit: str) -> str:
    return f"- {name} ({quantity:g}{unit})" if quantity else f"- {name}"


def build_prompt(req: GenerateRequest) -> str:
    ingredient_lines = "\n".join(_format_ingredient(i.name, i.quantity, i.unit) for i in req.ingredients)
    diets = [d for d in req.dietPreferences if d != "None"]
    cuisines = [c for c in req.cuisines if c != "Any"]
    example = {**EXAMPLE_RECIPE, "portions": req.portions}

    return "\n".join([
        f"Create exactly {RECIPE_COUNT} distinct recipes that primarily use the ingredients below.",
        "Common pantry staples (salt, pepper, oil, water, basic spices) may be assumed.",
        "",
        "Available ingredients:",
        ingredient_lines,
        "",
        f"Portions per recipe: {req.portions}",
        f"Cooking for: {req.people} people",
        f"Target cooking time: {TIME_HINT.get(req.cookingTime, TIME_HINT['medium'])}",
        f"Preferred cuisines: {', '.join(cuisines)}" if cuisines else "Cuisine: chef's choice",
        f"Dietary requirements (must respect all): {', '.join(diets)}" if diets else "Dietary requirements: none",
        "",
        'Respond with ONLY a JSON object, no markdown: {"recipes": [recipe, recipe, recipe]}.',
        "Each recipe looks exactly like this example (shortened to 2 steps here):",
        json.dumps(example, indent=2),
        "Nutrition values are per portion, in grams except calories (kcal).",
        "",
        "Instructions rules:",
        "- Give 6 to 10 steps. Each step is 1 to 3 full sentences.",
        "- Explain it plainly, the way you would tell a grandparent who is new to cooking:",
        "  say what to do, what it should look, smell or feel like, and roughly how long it takes.",
        "- Use simple everyday words. No chef jargon, no abbreviations.",
        "- Do NOT put the recipe name, cuisine, or serving count inside any step.",
        "- Do NOT number the steps yourself; just write the sentence(s).",
    ])


def to_response(drafts: RecipeDrafts, portions: int) -> RecipesResponse:
    """Add ids (1..n), enforce the requested portions, cut to RECIPE_COUNT."""
    recipes = [
        Recipe(**d.model_dump(exclude={"portions"}), id=i, portions=portions)
        for i, d in enumerate(drafts.recipes[:RECIPE_COUNT], start=1)
    ]
    return RecipesResponse(recipes=recipes)


async def generate_recipes(req: GenerateRequest) -> RecipesResponse:
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": build_prompt(req)},
    ]
    drafts = await complete_json(messages, RecipeDrafts)
    return to_response(drafts, req.portions)
