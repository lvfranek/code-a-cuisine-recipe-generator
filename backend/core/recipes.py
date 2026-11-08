"""Read access to the recipe records (data/recipes.jsonl)."""

from functools import lru_cache
from pathlib import Path

from core.config import get_settings
from core.schemas import RecipeRecord


def load_records(path: Path) -> list[RecipeRecord]:
    """Load and validate all records of a JSONL file (empty list if missing)."""
    if not path.exists():
        return []
    lines = path.read_text(encoding="utf-8").splitlines()
    return [RecipeRecord.model_validate_json(line) for line in lines if line.strip()]


@lru_cache
def records_by_id() -> dict[str, RecipeRecord]:
    """All records of the configured recipe file, by itemId (cached)."""
    return {r.itemId: r for r in load_records(get_settings().recipes_path)}


def get_record(item_id: str) -> RecipeRecord | None:
    return records_by_id().get(item_id)
