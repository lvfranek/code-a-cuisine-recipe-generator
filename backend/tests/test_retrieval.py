import hashlib

import numpy as np
import pytest

from core import recipes, retrieval
from core.config import get_settings
from core.retrieval import (
    IndexNotReadyError,
    SearchFilters,
    get_collection,
    ingredient_coverage,
    normalize_name,
    rerank,
    search_recipes,
    upsert_records,
)
from core.schemas import RecipeRecord


def fake_embed(texts):
    """Deterministic bag-of-words vectors (no model download in tests), L2-normalized."""
    out = []
    for text in texts:
        v = np.zeros(64)
        for word in text.lower().replace(",", " ").replace(".", " ").split():
            v[int(hashlib.md5(word.encode()).hexdigest(), 16) % 64] += 1
        out.append((v / (np.linalg.norm(v) or 1)).tolist())
    return out


def record(item_id, name, ingredients, cuisine="Other", diets=(), minutes=30, optional=()):
    return RecipeRecord.model_validate({
        "itemId": item_id,
        "name": name,
        "description": "Tasty.",
        "cuisine": cuisine,
        "dietTags": list(diets),
        "cookTimeMinutes": minutes,
        "servings": 2,
        "ingredients": [
            {"text": i, "name": i, "optional": i in optional} for i in ingredients
        ],
        "instructions": ["Cook."],
        "category": "Test",
        "source": {"name": "Test", "url": f"https://x/{item_id}", "license": "CC BY-SA 4.0"},
    })


RECORDS = [
    record("r1", "Tomato Pasta", ["pasta", "tomato", "garlic", "salt"], "Italian", ["Vegan", "Vegetarian"], 20),
    record("r2", "Chicken Rice", ["chicken", "rice", "onion"], "Other", [], 45),
    record("r3", "Bean Tacos", ["tortilla", "black bean", "tomato"], "Mexican", ["Vegan", "Vegetarian"], 15),
]


@pytest.fixture
def index(tmp_path, monkeypatch):
    """A small real ChromaDB index in a temp folder, with fake embeddings."""
    recipes_file = tmp_path / "recipes.jsonl"
    recipes_file.write_text("\n".join(r.model_dump_json() for r in RECORDS))
    monkeypatch.setenv("CHROMA_DIR", str(tmp_path / "chroma"))
    monkeypatch.setenv("RECIPES_FILE", str(recipes_file))
    monkeypatch.setattr(retrieval, "embed", fake_embed)
    get_settings.cache_clear()
    recipes.records_by_id.cache_clear()
    collection = get_collection(create=True)
    upsert_records(collection, RECORDS)
    yield collection
    recipes.records_by_id.cache_clear()


# ------------------------------- index -------------------------------


def test_upsert_twice_creates_no_duplicates(index):
    assert upsert_records(index, RECORDS) == 3


def test_missing_index_fails_early(tmp_path, monkeypatch):
    monkeypatch.setenv("CHROMA_DIR", str(tmp_path / "nope"))
    get_settings.cache_clear()
    with pytest.raises(IndexNotReadyError, match="No vector index"):
        get_collection()


def test_empty_collection_fails_early(tmp_path, monkeypatch):
    monkeypatch.setenv("CHROMA_DIR", str(tmp_path / "chroma"))
    get_settings.cache_clear()
    get_collection(create=True)
    with pytest.raises(IndexNotReadyError, match="empty"):
        get_collection()


def test_real_embeddings_are_normalized():
    vectors = np.array(fake_embed(["tomato pasta", "chicken"]))
    assert np.allclose(np.linalg.norm(vectors, axis=1), 1.0)


# ------------------------------- search -------------------------------


def test_search_finds_best_match(index):
    hits = search_recipes(["chicken", "rice", "onion"], k=3)
    assert hits[0].record.itemId == "r2"
    assert hits[0].missing == []


def test_diet_filter(index):
    hits = search_recipes(["chicken", "rice"], SearchFilters(diets=["Vegan"]), k=3)
    assert {h.record.itemId for h in hits} <= {"r1", "r3"}


def test_cuisine_and_time_filter(index):
    hits = search_recipes(["tomato"], SearchFilters(cuisines=["Mexican", "Italian"], max_minutes=15), k=3)
    assert [h.record.itemId for h in hits] == ["r3"]


def test_no_match_returns_empty_list(index):
    assert search_recipes(["tomato"], SearchFilters(cuisines=["Thai"])) == []


def test_unknown_filter_value_is_rejected(index):
    with pytest.raises(ValueError, match="Unknown filter"):
        search_recipes(["tomato"], SearchFilters(cuisines=["Martian"]))


def test_empty_ingredients_are_rejected(index):
    with pytest.raises(ValueError):
        search_recipes(["  "])


def test_where_clause():
    assert SearchFilters().to_where() is None
    assert SearchFilters(diets=["Vegan"]).to_where() == {"diet_vegan": True}
    assert SearchFilters(diets=["Gluten-Free"], max_minutes=30).to_where() == {
        "$and": [{"diet_gluten_free": True}, {"cookTimeMinutes": {"$lte": 30}}]
    }


# ------------------------------ ranking ------------------------------


def test_normalize_name():
    assert normalize_name("Tomatoes") == "tomato"
    assert normalize_name("Cherries") == "cherry"
    assert normalize_name("asparagus") == "asparagus"
    assert normalize_name("Swiss Cheese!") == "swiss cheese"


def test_coverage_counts_both_directions():
    pasta = RECORDS[0]  # pasta, tomato, garlic (+ salt = pantry)
    full, matched, missing = ingredient_coverage(pasta, ["pasta", "tomatoes", "garlic"])
    assert full == 1.0 and missing == []
    # Recipe fully covered, but uses only 1 of 4 user ingredients -> low score.
    lemon = record("x", "Lemon Water", ["lemon", "water"])
    score, _, _ = ingredient_coverage(lemon, ["lemon", "salmon", "dill", "rice"])
    assert score == pytest.approx(0.4)


def test_coverage_partial_word_match():
    r = record("x", "Melt", ["cheddar cheese", "bread"])
    score, matched, _ = ingredient_coverage(r, ["cheese", "bread"])
    assert matched == ["cheddar cheese", "bread"] and score == 1.0


def test_only_optional_ingredients_still_count():
    r = record("x", "Dashi", ["konbu", "bonito flake"], optional=("konbu", "bonito flake"))
    score, _, missing = ingredient_coverage(r, ["tofu"])
    assert score == 0.0 and missing == ["konbu", "bonito flake"]


def test_rerank_weights_are_parameters():
    a = retrieval.SearchHit(RECORDS[0], similarity=0.9, coverage=0.1, matched=[], missing=[])
    b = retrieval.SearchHit(RECORDS[1], similarity=0.5, coverage=0.9, matched=[], missing=[])
    assert rerank([a, b], w_similarity=1, w_coverage=0)[0] is a
    assert rerank([a, b], w_similarity=0, w_coverage=1)[0] is b
