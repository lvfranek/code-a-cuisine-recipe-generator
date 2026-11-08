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


@pytest.mark.parametrize(
    "diet, issue, false_alarm",
    [
        ("Vegetarian", "contains honey", True),
        ("Vegetarian", "uses eggs and butter", True),
        ("Keto", "butter is dairy", True),
        ("Gluten-Free", "butter is dairy", True),
        ("Dairy-Free", "contains eggs", True),
        ("Vegetarian", "contains honey and chicken stock", False),  # chicken is a real problem
        ("Vegan", "contains honey", False),  # honey really is not vegan
        ("Vegetarian", "Worcestershire sauce contains anchovy", False),
        ("Gluten-Free", "stock cube usually contains wheat", False),
    ],
)
def test_false_alarms_of_the_critic(diet, issue, false_alarm):
    from core.diet_rules import is_false_alarm

    assert is_false_alarm(diet, issue) is false_alarm
