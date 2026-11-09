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


def test_conflicts_name_the_ingredient_and_a_substitute():
    from core.diet_rules import conflicts

    found = conflicts(["tofu", "honey", "soy sauce", "coconut milk"], ["Vegan", "Gluten-Free"])
    assert found == [
        '"honey" breaks Vegan: do not use it; instead use maple syrup or agave syrup',
        '"soy sauce" breaks Gluten-Free: do not use it; instead use tamari (gluten-free soy sauce)',
    ]
    assert "zucchini noodles" in conflicts(["pasta"], ["Keto"])[0]
    assert "gluten-free" in conflicts(["pasta"], ["Gluten-Free"])[0]
    assert "coconut aminos" in conflicts(["soy sauce"], ["Paleo"])[0]
    assert conflicts(["tofu", "rice"], ["Vegan"]) == []


@pytest.mark.parametrize(
    "diet, line",
    [
        ("Dairy-Free", "2 tablespoons olive oil (instead of butter)"),
        ("Dairy-Free", "1/4 cup oat milk (instead of milk)"),
        ("Dairy-Free", "2 cups milk (oat or soy)"),
        ("Vegan", "2 tbsp maple syrup or agave syrup (to replace honey)"),
        ("Paleo", "2 tbsp coconut aminos (instead of soy sauce)"),
        ("Low-Carb", "2 medium zucchinis, spiralized into noodles"),
        ("Keto", "2 cups cauliflower rice"),
        ("Keto", "4 lettuce wraps"),
    ],
)
def test_substitutes_written_by_the_chef_are_not_flagged(diet, line):
    assert violations([line], diet) == []


@pytest.mark.parametrize(
    "diet, line",
    [
        ("Keto", "200 g rice noodles"),  # gluten-free, but not keto
        ("Dairy-Free", "2 tbsp olive oil or butter"),  # a real alternative, not a replacement
        ("Vegan", "1 cup milk"),
    ],
)
def test_exceptions_are_diet_specific(diet, line):
    assert violations([line], diet)


@pytest.mark.parametrize(
    "diet, line, flagged",
    [
        ("Vegan", "3 tbsp pesto", True),
        ("Vegan", "3 tbsp vegan pesto", False),
        ("Vegan", "1 cup kimchi, chopped", True),
        ("Vegetarian", "1 cup marshmallows", True),
        ("Vegetarian", "1 cup gelatin-free marshmallows", False),
        ("Vegetarian", "2 tbsp grated parmesan", False),  # rennet is ignored for vegetarians
        ("Gluten-Free", "1 stock cube", True),
        ("Gluten-Free", "1 gluten-free stock cube", False),
        ("Gluten-Free", "2 pieces naan bread", True),
        ("Vegetarian", "500 ml vegetable stock", False),
    ],
)
def test_hidden_ingredients_in_ready_made_products(diet, line, flagged):
    assert bool(violations([line], diet)) is flagged
