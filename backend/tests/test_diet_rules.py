import pytest

from core.diet_rules import violations


@pytest.mark.parametrize(
    "diet, line",
    [
        ("Vegan", "2 eggs"),
        ("Vegan", "1 tbsp butter"),
        ("Vegan", "2 tbsp honey"),
        ("Vegan", "100 g cheddar cheese"),
        ("Vegetarian", "2 cups chicken broth"),
        ("Vegetarian", "1 tsp Worcestershire sauce"),
        ("Vegetarian", "4 slices bacon"),
        ("Gluten-Free", "2 tbsp soy sauce"),
        ("Gluten-Free", "200 g spaghetti"),
        ("Gluten-Free", "1 cup flour"),
        ("Dairy-Free", "50 ml heavy cream"),
        ("Keto", "100 g rice"),
        ("Keto", "1 sweet potato"),
        ("Paleo", "1 block tofu"),
    ],
)
def test_clear_violations_are_found(diet, line):
    assert violations([line], diet)


@pytest.mark.parametrize(
    "diet, line",
    [
        ("Vegan", "1 eggplant"),
        ("Vegan", "200 ml coconut milk"),
        ("Vegan", "2 tbsp peanut butter"),
        ("Vegan", "1 butternut squash"),
        ("Vegan", "4 slices vegan bacon"),
        ("Vegetarian", "500 ml vegetable broth"),
        ("Gluten-Free", "2 tbsp tamari"),
        ("Gluten-Free", "1 tbsp gluten-free soy sauce"),
        ("Gluten-Free", "100 g rice flour"),
        ("Gluten-Free", "2 corn tortillas"),
        ("Dairy-Free", "1 tsp cream of tartar"),
        ("Keto", "1 tbsp sugar-free syrup"),
        ("Paleo", "1 sweet potato"),
        ("Paleo", "2 tbsp honey"),
    ],
)
def test_fine_ingredients_are_not_flagged(diet, line):
    assert violations([line], diet) == []


def test_violation_names_the_trigger_word():
    assert violations(["2 tbsp soy sauce"], "Gluten-Free") == ['"2 tbsp soy sauce" (soy sauce)']


def test_unknown_diet_has_no_rules():
    assert violations(["2 eggs"], "Martian") == []
