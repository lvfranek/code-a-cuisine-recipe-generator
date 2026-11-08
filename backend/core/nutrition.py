"""Real nutrition values from USDA FoodData Central, calculated in code.

1. Each ingredient (generic English name + grams, from the nutrition agent)
   is matched to a USDA food via vector search in the `usda_foods` collection
   (same embedding model as the recipes, one collection per data type).
2. kcal/protein/carbs/fat = sum(per100g * grams / 100) / portions. No LLM math.
3. Matches are cached in memory: the same ingredient is looked up only once.
"""

import logging
import re
from dataclasses import dataclass, field
from functools import lru_cache

from core.config import get_settings
from core.retrieval import embed, get_client, normalize_name
from core.schemas import Nutrition, UsdaFood

log = logging.getLogger(__name__)

COLLECTION = "usda_foods"
SOURCE = "USDA FoodData Central"
MIN_SIMILARITY = 0.55  # below this the match is a guess, not a lookup
MIN_COVERAGE = 0.8  # share of the recipe weight that must be matched to trust the result
CANDIDATES = 20

# Very common, ambiguous ingredients -> the USDA entry a recipe almost always
# means (raw / uncooked amounts, plain variety). Checked before vector search.
ALIASES = {
    "egg": "Egg, whole, raw, fresh",
    "flour": "Wheat flour, white, all-purpose, enriched, bleached",
    "all purpose flour": "Wheat flour, white, all-purpose, enriched, bleached",
    "milk": "Milk, whole, 3.25% milkfat, with added vitamin D",
    "rice": "Rice, white, long-grain, regular, raw, enriched",
    "white rice": "Rice, white, long-grain, regular, raw, enriched",
    "long grain rice": "Rice, white, long-grain, regular, raw, enriched",
    "brown rice": "Rice, brown, long-grain, raw (Includes foods for USDA's Food Distribution Program)",
    "pasta": "Pasta, dry, enriched",
    "spaghetti": "Pasta, dry, enriched",
    "penne": "Pasta, dry, enriched",
    "noodle": "Pasta, dry, enriched",
    "salmon": "Fish, salmon, Atlantic, farmed, raw",
    "coconut milk": "Nuts, coconut milk, raw (liquid expressed from grated meat and water)",
    "oat": "Oats (Includes foods for USDA's Food Distribution Program)",
    "rolled oat": "Oats (Includes foods for USDA's Food Distribution Program)",
    "bacon": "Pork, cured, bacon, unprepared",
    "chicken broth": "Soup, chicken broth, ready-to-serve",
    "chicken stock": "Soup, chicken broth, ready-to-serve",
    "vegetable broth": "Soup, vegetable broth, ready to serve",
    "vegetable stock": "Soup, vegetable broth, ready to serve",
    "bell pepper": "Peppers, sweet, red, raw",
    "red bell pepper": "Peppers, sweet, red, raw",
    "tofu": "Tofu, raw, firm, prepared with calcium sulfate",
    "chicken breast": "Chicken, broiler or fryers, breast, skinless, boneless, meat only, raw",
    "chicken": "Chicken, broiler or fryers, breast, skinless, boneless, meat only, raw",
    "tomato": "Tomatoes, red, ripe, raw, year round average",
    "potato": "Potatoes, flesh and skin, raw",
    "cheddar cheese": "Cheese, cheddar, sharp, sliced",
    "cheese": "Cheese, cheddar, sharp, sliced",
    "ground beef": "Beef, ground, 80% lean meat / 20% fat, raw",
    "soy sauce": "Soy sauce made from soy and wheat (shoyu)",
    "heavy cream": "Cream, fluid, heavy whipping",
    "apple": "Apples, raw, with skin (Includes foods for USDA's Food Distribution Program)",
    "tuna": "Fish, tuna, light, canned in water, drained solids (Includes foods for USDA's Food Distribution Program)",
    "sweet potato": "Sweet potato, raw, unprepared (Includes foods for USDA's Food Distribution Program)",
    "beef broth": "Soup, beef broth or bouillon canned, ready-to-serve",
    "beef stock": "Soup, beef broth or bouillon canned, ready-to-serve",
    "mayonnaise": "Salad dressing, mayonnaise, regular",
    "tomato paste": "Tomato products, canned, paste, without salt added (Includes foods for USDA's Food Distribution Program)",
    "kidney bean": "Beans, kidney, red, mature seeds, raw",
    "sour cream": "Cream, sour, cultured",
    "cinnamon": "Spices, cinnamon, ground",
    "vegetable oil": "Oil, soybean, salad or cooking",
    "cooking oil": "Oil, soybean, salad or cooking",
}

# Words that make a USDA entry a worse default than the plain food.
_PROCESSED = re.compile(r"\b(canned|frozen|dried|dehydrated|fried|breaded|sweetened|prepared|mix|infant|commercial|cooked)\b", re.I)
_DISH = re.compile(r"\b(salad|strudel|pie|cake|sandwich|bar|pudding|casserole|skin|babyfood)\b", re.I)
_SUBSTITUTE = re.compile(r"\b(meatless|imitation|substitute|vegetarian|nonfat|fat free|reduced fat|low fat|low sodium)\b", re.I)
_BRAND = re.compile(r"\b[A-Z][A-Z'&]{2,}\b|pillsbury|kraft|kellogg|campbell|hormel|oscar mayer|george weston", re.I)
_BRAND_CASE = re.compile(r"\b[A-Z]{3,}\b")


@dataclass
class FoodMatch:
    food: UsdaFood
    similarity: float


@dataclass
class NutritionResult:
    nutrition: Nutrition  # per portion
    coverage: float  # matched grams / total grams
    total_grams: float
    unmatched: list[str] = field(default_factory=list)

    @property
    def reliable(self) -> bool:
        return self.total_grams > 0 and self.coverage >= MIN_COVERAGE


# --------------------------------------------------------------------------
# Index
# --------------------------------------------------------------------------


def food_text(food: UsdaFood) -> str:
    return food.description


def upsert_foods(collection, foods: list[UsdaFood], batch_size: int = 256) -> int:
    for start in range(0, len(foods), batch_size):
        batch = foods[start : start + batch_size]
        collection.upsert(
            ids=[str(f.fdcId) for f in batch],
            documents=[food_text(f) for f in batch],
            metadatas=[
                {"fdcId": f.fdcId, "description": f.description, "category": f.category, "food": f.model_dump_json()}
                for f in batch
            ],
            embeddings=embed([food_text(f) for f in batch]),
        )
    return collection.count()


@lru_cache
def _collection():
    from core.retrieval import IndexNotReadyError

    if not get_settings().chroma_path.exists():
        raise IndexNotReadyError("No vector index. Run: uv run python -m ingest.build_index")
    try:
        collection = get_client().get_collection(COLLECTION, embedding_function=None)
    except Exception as err:
        raise IndexNotReadyError(f"Collection '{COLLECTION}' not found. Run: uv run python -m ingest.build_index") from err
    if collection.count() == 0:
        raise IndexNotReadyError(f"Collection '{COLLECTION}' is empty. Run: uv run python -m ingest.build_index")
    return collection


# --------------------------------------------------------------------------
# Matching
# --------------------------------------------------------------------------


def word_overlap(name: str, description: str) -> float:
    """Share of the ingredient's words that appear as whole words in the USDA name."""
    words = name.split()
    desc_words = set(normalize_name(description).split())
    return sum(1 for w in words if w in desc_words) / len(words) if words else 0.0


def rank_score(name: str, food: UsdaFood, similarity: float) -> float:
    """Similarity plus preferences: all words present, plain, raw, unbranded wins."""
    desc = food.description
    head = normalize_name(desc.split(",")[0])
    score = similarity + 0.30 * word_overlap(name, desc)  # 'egg' must not become 'Eggnog'
    if head and (head == name or head in name.split() or name.split()[-1] == head):
        score += 0.10  # 'Tomatoes, red, ripe, raw' for 'tomato'
    if re.search(r"\braw\b", desc, re.I):
        score += 0.05
    if _PROCESSED.search(desc) and not _PROCESSED.search(name):
        score -= 0.05
    if _SUBSTITUTE.search(desc) and not _SUBSTITUTE.search(name):
        score -= 0.20  # 'bacon' must not become 'Bacon, meatless'
    if _DISH.search(re.sub(r"salad or cooking|salad dressing", "", desc, flags=re.I)) and not _DISH.search(name):
        score -= 0.20  # 'apple' must not become 'Strudel, apple'
    if re.search(r"\boils?\b", desc, re.I) and "oil" not in name.split():
        score -= 0.30  # 'salmon' must not become 'Fish oil, salmon'
    if _BRAND.search(desc) and _BRAND_CASE.search(desc):
        score -= 0.15
    return score - 0.002 * len(desc.split())  # prefer short, generic entries


def match_foods(names: list[str]) -> list[FoodMatch | None]:
    """Best USDA food for each ingredient name (None if nothing is close enough)."""
    return [_match_one(normalize_name(n)) for n in names]


@lru_cache
def _by_description(description: str) -> UsdaFood | None:
    hit = _collection().get(where={"description": description}, include=["metadatas"])
    metas = hit.get("metadatas") or []
    return UsdaFood.model_validate_json(metas[0]["food"]) if metas else None


@lru_cache(maxsize=4096)
def _match_one(name: str) -> FoodMatch | None:
    if not name:
        return None
    if name in ALIASES and (food := _by_description(ALIASES[name])):
        return FoodMatch(food, 1.0)
    result = _collection().query(query_embeddings=embed([name]), n_results=CANDIDATES)
    best: tuple[float, FoodMatch] | None = None
    for meta, distance in zip(result["metadatas"][0], result["distances"][0]):
        similarity = 1.0 - float(distance)
        if similarity < MIN_SIMILARITY:
            continue
        food = UsdaFood.model_validate_json(meta["food"])
        score = rank_score(name, food, similarity)
        if best is None or score > best[0]:
            best = (score, FoodMatch(food, similarity))
    return best[1] if best else None


# --------------------------------------------------------------------------
# Calculation
# --------------------------------------------------------------------------


def calculate(items: list[tuple[str, float]], portions: int) -> NutritionResult:
    """items: (generic food name, grams for the whole recipe). Returns values per portion."""
    items = [(n, g) for n, g in items if g and g > 0]
    total = sum(g for _, g in items)
    sums = {"calories": 0.0, "protein": 0.0, "carbs": 0.0, "fat": 0.0}
    matched_grams, unmatched = 0.0, []
    for (name, grams), match in zip(items, match_foods([n for n, _ in items])):
        if match is None:
            unmatched.append(name)
            continue
        matched_grams += grams
        for key in sums:
            sums[key] += getattr(match.food.per100g, key) * grams / 100
    portions = max(1, portions)
    per_portion = Nutrition(
        calories=round(sums["calories"] / portions),
        protein=round(sums["protein"] / portions, 1),
        carbs=round(sums["carbs"] / portions, 1),
        fat=round(sums["fat"] / portions, 1),
    )
    coverage = matched_grams / total if total else 0.0
    return NutritionResult(per_portion, coverage, total, unmatched)
