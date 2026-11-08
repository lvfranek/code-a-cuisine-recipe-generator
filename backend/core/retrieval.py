"""Recipe search in ChromaDB (retrieval layer, independent of any LLM).

Hybrid retrieval:
1. Vector search: the user's ingredients vs. each recipe's ingredient text.
2. Metadata filters (`where`): diet, cuisine, max cooking time.
3. Re-ranking: vector similarity combined with "ingredient coverage"
   (how many of the recipe's ingredients the user actually has).

Embeddings: all-MiniLM-L6-v2 (ONNX, runs on CPU, no PyTorch), L2-normalized,
cosine distance. Index and queries always use the same `embed()` function.
"""

import logging
import re
from dataclasses import dataclass
from functools import lru_cache

import numpy as np

from core.config import get_settings
from core.recipes import get_record
from core.schemas import CUISINE_VALUES, DIET_VALUES, RecipeRecord

log = logging.getLogger(__name__)

COLLECTION = "recipes"
EMBEDDING_MODEL = "all-MiniLM-L6-v2 (ONNX)"

# Default fusion weights (see rerank). Similarity finds "similar dishes",
# coverage prefers recipes the user can cook with what they have.
W_SIMILARITY = 0.5
W_COVERAGE = 0.5
MIN_SIMILARITY = 0.15  # below this a hit is noise, even if it ranks first

# Always assumed to be at home; never count as "missing".
PANTRY_STAPLES = {
    "salt", "pepper", "black pepper", "water", "oil", "olive oil", "vegetable oil",
    "cooking oil", "sugar", "flour", "all purpose flour", "butter", "ice",
}


class IndexNotReadyError(RuntimeError):
    """The vector index is missing or empty. Build it first."""


# --------------------------------------------------------------------------
# Embeddings
# --------------------------------------------------------------------------


@lru_cache
def _model():
    from chromadb.utils.embedding_functions import ONNXMiniLM_L6_V2

    return ONNXMiniLM_L6_V2()


def embed(texts: list[str]) -> list[list[float]]:
    """Embed texts and L2-normalize them (so cosine similarity is well defined)."""
    vectors = np.asarray(_model()(texts), dtype=np.float32)
    norms = np.linalg.norm(vectors, axis=1, keepdims=True)
    return (vectors / np.clip(norms, 1e-12, None)).tolist()


# --------------------------------------------------------------------------
# Documents (record -> what goes into the index)
# --------------------------------------------------------------------------


def diet_key(diet: str) -> str:
    """'Gluten-Free' -> 'diet_gluten_free' (Chroma metadata cannot hold lists)."""
    return "diet_" + diet.lower().replace("-", "_")


def retrieval_text(record: RecipeRecord) -> str:
    """Ingredients first (that is what users search with), then name and dish type."""
    ingredients = ", ".join(i.name for i in record.ingredients if not i.optional)
    return f"Ingredients: {ingredients}. Dish: {record.name} ({record.category or 'recipe'})."


def to_document(record: RecipeRecord) -> tuple[str, str, dict]:
    """Record -> (doc_id, retrieval text, filterable metadata)."""
    metadata = {
        "itemId": record.itemId,
        "name": record.name,
        "cuisine": record.cuisine,
        "category": record.category or "",
        "cookTimeMinutes": record.cookTimeMinutes,
        "servings": record.servings,
        "source": record.source.name,
        **{diet_key(d): d in record.dietTags for d in DIET_VALUES},
    }
    return record.itemId, retrieval_text(record), metadata


# --------------------------------------------------------------------------
# Index access
# --------------------------------------------------------------------------


def get_client():
    import chromadb

    return chromadb.PersistentClient(path=str(get_settings().chroma_path))


def get_collection(create: bool = False):
    """Open the recipe collection. Fails early with a clear message if not built."""
    path = get_settings().chroma_path
    if not create and not path.exists():
        raise IndexNotReadyError(f"No vector index at {path}. Run: uv run python -m ingest.build_index")
    client = get_client()
    if create:
        return client.get_or_create_collection(
            COLLECTION, configuration={"hnsw": {"space": "cosine"}}, embedding_function=None
        )
    try:
        collection = client.get_collection(COLLECTION, embedding_function=None)
    except Exception as err:
        raise IndexNotReadyError(f"Collection '{COLLECTION}' not found. Run: uv run python -m ingest.build_index") from err
    if collection.count() == 0:
        raise IndexNotReadyError(f"Collection '{COLLECTION}' is empty. Run: uv run python -m ingest.build_index")
    return collection


def upsert_records(collection, records: list[RecipeRecord], batch_size: int = 128) -> int:
    """Add or update records by itemId. Re-running never creates duplicates."""
    for start in range(0, len(records), batch_size):
        ids, docs, metas = zip(*(to_document(r) for r in records[start : start + batch_size]))
        collection.upsert(ids=list(ids), documents=list(docs), metadatas=list(metas), embeddings=embed(list(docs)))
    return collection.count()


# --------------------------------------------------------------------------
# Search
# --------------------------------------------------------------------------


@dataclass
class SearchFilters:
    diets: list[str] | None = None  # recipe must satisfy ALL
    cuisines: list[str] | None = None  # recipe must be ONE of them
    max_minutes: int | None = None

    def validate(self) -> None:
        """Filter values must exist in the metadata, otherwise results are silently empty."""
        unknown = [d for d in self.diets or [] if d not in DIET_VALUES]
        unknown += [c for c in self.cuisines or [] if c not in CUISINE_VALUES]
        if unknown:
            raise ValueError(f"Unknown filter value(s): {unknown}. Allowed: {list(DIET_VALUES) + list(CUISINE_VALUES)}")
        if self.max_minutes is not None and self.max_minutes < 1:
            raise ValueError("max_minutes must be at least 1")

    def to_where(self) -> dict | None:
        """Build a Chroma `where` clause (None = no filter)."""
        clauses: list[dict] = [{diet_key(d): True} for d in self.diets or []]
        if self.cuisines:
            clauses.append({"cuisine": {"$in": list(self.cuisines)}})
        if self.max_minutes:
            clauses.append({"cookTimeMinutes": {"$lte": int(self.max_minutes)}})
        if not clauses:
            return None
        return clauses[0] if len(clauses) == 1 else {"$and": clauses}


@dataclass
class SearchHit:
    record: RecipeRecord
    similarity: float  # 1 - cosine distance
    coverage: float  # share of the recipe's main ingredients the user has
    matched: list[str]
    missing: list[str]
    score: float = 0.0


def normalize_name(name: str) -> str:
    """Lowercase, letters only, simple singular ('Tomatoes' -> 'tomato')."""
    words = re.sub(r"[^a-z ]", " ", name.lower()).split()
    out = []
    for w in words:
        if w.endswith("oes") or w.endswith("ies"):
            w = w[:-3] + ("o" if w.endswith("oes") else "y")
        elif w.endswith("s") and not w.endswith(("ss", "us", "is")) and len(w) > 3:
            w = w[:-1]
        out.append(w)
    return " ".join(out)


def _have(ingredient: str, available: set[str]) -> bool:
    """'cheddar cheese' matches user 'cheese'; 'cheese' matches user 'cheddar cheese'."""
    words = set(ingredient.split())
    return any(a == ingredient or set(a.split()) <= words or words <= set(a.split()) for a in available)


def _needed(record: RecipeRecord) -> list[str]:
    """Main ingredients of a recipe (normalized, no pantry staples).
    If every ingredient is optional (e.g. 'use X or Y'), all of them count."""
    names = [normalize_name(i.name) for i in record.ingredients if not i.optional]
    if not any(n not in PANTRY_STAPLES for n in names):
        names = [normalize_name(i.name) for i in record.ingredients]
    return [n for n in dict.fromkeys(names) if n and n not in PANTRY_STAPLES]


def ingredient_coverage(record: RecipeRecord, user_ingredients: list[str]) -> tuple[float, list[str], list[str]]:
    """Ingredient match in both directions, 0..1, plus matched / missing recipe ingredients.

    - recipe side: share of the recipe's main ingredients the user has
    - user side:   share of the user's ingredients the recipe uses
    Combined with the harmonic mean (like F1), so a recipe only scores high if
    the user can cook it AND it uses what they have. Pantry staples are free.
    """
    available = {normalize_name(i) for i in user_ingredients if i.strip()}
    needed = _needed(record)
    if not needed or not available:
        return 0.0, [], needed
    matched = [n for n in needed if _have(n, available)]
    missing = [n for n in needed if n not in matched]
    used = [a for a in available if any(_have(n, {a}) for n in needed)]

    recipe_side = len(matched) / len(needed)
    user_side = len(used) / len(available)
    if recipe_side + user_side == 0:
        return 0.0, matched, missing
    return 2 * recipe_side * user_side / (recipe_side + user_side), matched, missing


def rerank(hits: list[SearchHit], w_similarity: float = W_SIMILARITY, w_coverage: float = W_COVERAGE) -> list[SearchHit]:
    """Weighted sum of similarity and coverage. Both are already on a 0..1 scale."""
    for h in hits:
        h.score = w_similarity * h.similarity + w_coverage * h.coverage
    return sorted(hits, key=lambda h: h.score, reverse=True)


def _unwrap(result: dict) -> list[tuple[str, float]]:
    """Chroma returns lists of lists (one per query). We always send one query."""
    ids = (result.get("ids") or [[]])[0]
    distances = (result.get("distances") or [[]])[0]
    return list(zip(ids, distances))


def search_recipes(
    ingredients: list[str],
    filters: SearchFilters | None = None,
    k: int = 5,
    candidates: int = 30,
    w_similarity: float = W_SIMILARITY,
    w_coverage: float = W_COVERAGE,
) -> list[SearchHit]:
    """Find the best recipes for the given ingredients. Empty list = nothing matches the filters."""
    ingredients = [i.strip() for i in ingredients if i and i.strip()]
    if not ingredients:
        raise ValueError("Give at least one ingredient to search with.")
    filters = filters or SearchFilters()
    filters.validate()

    collection = get_collection()
    query = f"Ingredients: {', '.join(ingredients)}."
    result = collection.query(
        query_embeddings=embed([query]),
        n_results=min(candidates, collection.count()),
        where=filters.to_where(),
    )

    hits = []
    for item_id, distance in _unwrap(result):
        record = get_record(item_id)
        if record is None:
            log.warning("Index has %s but recipes file does not. Rebuild the index.", item_id)
            continue
        similarity = 1.0 - float(distance)
        if similarity < MIN_SIMILARITY:
            continue
        coverage, matched, missing = ingredient_coverage(record, ingredients)
        hits.append(SearchHit(record, similarity, coverage, matched, missing))

    if not hits:
        log.info("No recipes match %s with filters %s", ingredients, filters)
    return rerank(hits, w_similarity, w_coverage)[:k]
