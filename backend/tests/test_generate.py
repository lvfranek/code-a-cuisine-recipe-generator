import asyncio
import json

from core import generate
from core.generate import build_prompt, generate_recipes
from core.schemas import GenerateRequest

REQUEST = GenerateRequest.model_validate({
    "ingredients": [{"name": "Tomatoes", "quantity": 300, "unit": "g"}, {"name": "Basil"}],
    "portions": 4,
    "cookingTime": "quick",
    "cuisines": ["Any", "Italian"],
    "dietPreferences": ["Vegan"],
})


def draft(name):
    return {
        "name": name,
        "description": "Nice.",
        "cookTime": "15 min",
        "cuisine": "Italian",
        "dietTags": ["Vegan"],
        "portions": 1,  # wrong on purpose: must be replaced by the requested 4
        "nutrition": {"calories": 300, "protein": 8, "carbs": 40, "fat": 9},
        "ingredients": ["300 g tomatoes"],
        "instructions": ["Chop.", "Serve."],
    }


def test_prompt_contains_user_input():
    prompt = build_prompt(REQUEST)
    assert "- Tomatoes (300g)" in prompt
    assert "- Basil\n" in prompt
    assert "Portions per recipe: 4" in prompt
    assert "about 15 minutes" in prompt
    assert "Preferred cuisines: Italian" in prompt
    assert "Dietary requirements (must respect all): Vegan" in prompt


def test_generate_adds_ids_portions_and_cuts_to_three(monkeypatch):
    answer = json.dumps({"recipes": [draft(f"R{i}") for i in range(4)]})

    async def fake_chat(messages, **kwargs):
        return answer

    monkeypatch.setattr("core.llm.chat", fake_chat)
    result = asyncio.run(generate_recipes(REQUEST))

    assert [r.id for r in result.recipes] == [1, 2, 3]
    assert all(r.portions == 4 for r in result.recipes)
    assert generate.RECIPE_COUNT == 3
