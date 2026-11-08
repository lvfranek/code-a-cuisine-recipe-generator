import pytest
from pydantic import ValidationError

from core.schemas import Recipe, RecipesResponse

# Same shape that api/generate.js sends to the frontend today.
FRONTEND_EXAMPLE = {
    "recipes": [
        {
            "id": 1,
            "name": "Tomato Pasta",
            "description": "Quick and fresh.",
            "cookTime": "25 min",
            "cuisine": "Italian",
            "dietTags": ["Vegetarian"],
            "portions": 2,
            "nutrition": {"calories": 520, "protein": 18, "carbs": 80, "fat": 12},
            "ingredients": ["200g pasta", "3 tomatoes"],
            "instructions": ["Boil the pasta.", "Mix with the tomatoes."],
        }
    ]
}


def test_frontend_example_round_trips_unchanged():
    parsed = RecipesResponse.model_validate(FRONTEND_EXAMPLE)
    assert parsed.model_dump() == FRONTEND_EXAMPLE


def test_missing_optional_fields_get_same_defaults_as_js():
    recipe = Recipe.model_validate({"id": 1, "name": "Soup"})
    assert recipe.cookTime == "30 min"
    assert recipe.cuisine == "Various"
    assert recipe.portions == 2
    assert recipe.nutrition.calories == 0
    assert recipe.dietTags == []


def test_negative_nutrition_is_rejected():
    with pytest.raises(ValidationError):
        Recipe.model_validate({"id": 1, "name": "X", "nutrition": {"calories": -5}})
