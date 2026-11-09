"""Independent diet judge for the evaluation.

Uses a different model family (Claude) than the app (Gemini), so the app's own
diet checker is not grading itself. Same diet definitions as the app.
"""

from pydantic import BaseModel, Field

from core.agents.config import DIET_DEFINITIONS
from core.llm import complete_json
from core.schemas import Recipe

JUDGE_MODEL = "anthropic/claude-haiku-5.5"

JUDGE = {
    "role": "Diet Auditor",
    "goal": "Decide for each recipe whether it breaks any of the required diets.",
    "backstory": (
        "You are an independent dietitian auditing recipes from another system. You are precise: "
        "you report an ingredient only if it clearly breaks the diet definition. Ingredients that are "
        "explicitly compliant variants (e.g. 'gluten-free soy sauce', 'vegan butter', 'tamari') are fine. "
        "Store-bought products count by what they usually contain: a product that normally contains a "
        "forbidden ingredient is a violation unless the recipe explicitly names a compliant version."
    ),
}


class Violation(BaseModel):
    diet: str
    ingredient: str = Field(max_length=200)


class RecipeVerdict(BaseModel):
    index: int = Field(ge=1)
    violations: list[Violation] = Field(default_factory=list)


class Verdicts(BaseModel):
    recipes: list[RecipeVerdict]


def build_judge_messages(recipes: list[Recipe], diets: list[str]) -> list[dict]:
    definitions = "\n".join(f"- {d}: {DIET_DEFINITIONS[d]}" for d in diets)
    blocks = []
    for i, r in enumerate(recipes, start=1):
        ingredients = "\n".join(f"  - {line}" for line in r.ingredients)
        steps = " ".join(r.instructions)
        blocks.append(f"Recipe {i}: {r.name}\nIngredients:\n{ingredients}\nSteps: {steps}")
    system = f"You are the {JUDGE['role']}.\nGoal: {JUDGE['goal']}\n{JUDGE['backstory']}"
    user = "\n\n".join([
        f"Required diets: {', '.join(diets)}\nDefinitions:\n{definitions}",
        "Check the ingredients AND the steps (an ingredient added in a step counts).",
        "\n\n".join(blocks),
        'Return ONLY JSON: {"recipes": [{"index": 1, "violations": [{"diet": "Vegan", "ingredient": "honey"}]}, '
        '{"index": 2, "violations": []}]}. One entry per recipe. diet must be one of the required diets.',
    ])
    return [{"role": "system", "content": system}, {"role": "user", "content": user}]


async def judge(recipes: list[Recipe], diets: list[str]) -> dict[int, list[Violation]]:
    """Violations of the required diets per recipe index (1-based)."""
    verdicts = await complete_json(build_judge_messages(recipes, diets), Verdicts, temperature=0, model=JUDGE_MODEL)
    out: dict[int, list[Violation]] = {i: [] for i in range(1, len(recipes) + 1)}
    for v in verdicts.recipes:
        if v.index in out:
            out[v.index] = [x for x in v.violations if x.diet in diets]
    return out
