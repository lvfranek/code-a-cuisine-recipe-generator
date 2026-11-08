import pytest
from pydantic import ValidationError

from core.schemas import GenerateRequest, Recipe, RecipesResponse

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
    assert parsed.model_dump(exclude_none=True) == FRONTEND_EXAMPLE


def test_missing_optional_fields_get_same_defaults_as_js():
    recipe = Recipe.model_validate({"id": 1, "name": "Soup", "ingredients": ["water"], "instructions": ["Boil."]})
    assert recipe.cookTime == "30 min"
    assert recipe.cuisine == "Various"
    assert recipe.nutrition.calories == 0
    assert recipe.dietTags == []


def test_recipe_without_steps_is_rejected():
    with pytest.raises(ValidationError):
        Recipe.model_validate({"id": 1, "name": "X", "ingredients": ["a"], "instructions": []})


def test_negative_nutrition_is_rejected():
    with pytest.raises(ValidationError):
        Recipe.model_validate(
            {"id": 1, "name": "X", "ingredients": ["a"], "instructions": ["b"], "nutrition": {"calories": -5}}
        )


# ---------------- GenerateRequest (port of lib/validate.js) ----------------


def test_request_is_cleaned_like_js():
    req = GenerateRequest.model_validate({
        "ingredients": [
            {"name": "  Toma\ntoes  ", "quantity": "300", "unit": "g"},
            {"name": "Rice", "quantity": -4, "unit": "kg"},  # bad quantity + unit
            {"name": "   "},  # empty name -> dropped
            "not an object",  # dropped
        ],
        "portions": 99,
        "people": "abc",
        "cookingTime": "forever",
        "cuisines": ["Italian", "Italian", "Martian"],
        "dietPreferences": ["Vegan", "Carnivore"],
    })
    assert [i.model_dump() for i in req.ingredients] == [
        {"name": "Toma toes", "quantity": 300, "unit": "g"},
        {"name": "Rice", "quantity": 0, "unit": "g"},
    ]
    assert req.portions == 20
    assert req.people == 2
    assert req.cookingTime == "medium"
    assert req.cuisines == ["Italian"]
    assert req.dietPreferences == ["Vegan"]


def test_request_needs_at_least_one_ingredient():
    with pytest.raises(ValidationError, match="Add at least one ingredient"):
        GenerateRequest.model_validate({"ingredients": [{"name": ""}]})


def test_request_rejects_too_many_ingredients():
    with pytest.raises(ValidationError, match="Too many ingredients"):
        GenerateRequest.model_validate({"ingredients": [{"name": f"i{n}"} for n in range(21)]})


def test_ingredient_name_is_cut_to_50_chars():
    req = GenerateRequest.model_validate({"ingredients": [{"name": "x" * 80}]})
    assert len(req.ingredients[0].name) == 50
