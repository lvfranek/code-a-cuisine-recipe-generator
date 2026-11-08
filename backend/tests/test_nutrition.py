import pytest

from core import nutrition
from core.nutrition import FoodMatch, calculate, rank_score, word_overlap
from core.schemas import UsdaFood


def food(description, calories, protein=0, carbs=0, fat=0):
    return UsdaFood(
        fdcId=abs(hash(description)) % 10**6,
        description=description,
        category="Test",
        per100g={"calories": calories, "protein": protein, "carbs": carbs, "fat": fat},
    )


FOODS = {
    "rice": food("Rice, white, long-grain, regular, raw, enriched", 365, 7.1, 80, 0.7),
    "chicken breast": food("Chicken, breast, raw", 120, 22.5, 0, 2.6),
    "olive oil": food("Oil, olive", 884, 0, 0, 100),
}


@pytest.fixture
def fake_matches(monkeypatch):
    monkeypatch.setattr(
        nutrition, "match_foods", lambda names: [FoodMatch(FOODS[n], 0.9) if n in FOODS else None for n in names]
    )


def test_calculation_is_done_in_code(fake_matches):
    # 200 g rice + 300 g chicken + 20 g oil, 2 portions
    result = calculate([("rice", 200), ("chicken breast", 300), ("olive oil", 20)], portions=2)
    assert result.nutrition.calories == round((730 + 360 + 176.8) / 2)
    assert result.nutrition.protein == round((14.2 + 67.5) / 2, 1)
    assert result.nutrition.fat == round((1.4 + 7.8 + 20) / 2, 1)
    assert result.coverage == 1.0 and result.reliable


def test_unmatched_weight_lowers_coverage(fake_matches):
    result = calculate([("rice", 200), ("dragon fruit", 800)], portions=1)
    assert result.unmatched == ["dragon fruit"]
    assert result.coverage == pytest.approx(0.2)
    assert not result.reliable


def test_zero_grams_are_ignored(fake_matches):
    result = calculate([("water", 0), ("rice", 100)], portions=1)
    assert result.total_grams == 100 and result.nutrition.calories == 365


def test_word_overlap():
    assert word_overlap("egg", "Egg, whole, raw, fresh") == 1.0
    assert word_overlap("egg", "Eggnog") == 0.0


@pytest.mark.parametrize(
    "name, good, bad",
    [
        ("egg", "Egg, whole, raw, fresh", "Eggnog"),
        ("salmon", "Fish, salmon, Atlantic, raw", "Fish oil, salmon"),
        ("bacon", "Pork, cured, bacon, unprepared", "Bacon, meatless"),
        ("apple", "Apples, raw, with skin", "Strudel, apple"),
        ("tomato", "Tomatoes, red, ripe, raw", "Tomatoes, red, ripe, canned, packed in tomato juice"),
    ],
)
def test_ranking_prefers_the_plain_food(name, good, bad):
    # Even with equal (or slightly worse) embedding similarity, the plain food wins.
    assert rank_score(name, food(good, 1), 0.70) > rank_score(name, food(bad, 1), 0.75)
