import pytest

from core import recipes
from core.config import get_settings


@pytest.fixture(autouse=True)
def fake_settings(monkeypatch, tmp_path):
    """Tests never use the real key from backend/.env, never call OpenRouter
    and never touch the real recipe index (unless a test sets one up)."""
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
    monkeypatch.setenv("MAX_REPAIR_ATTEMPTS", "5")
    monkeypatch.setenv("CHROMA_DIR", str(tmp_path / "no-index"))
    monkeypatch.setenv("RECIPES_FILE", str(tmp_path / "no-recipes.jsonl"))
    get_settings.cache_clear()
    recipes.records_by_id.cache_clear()
    yield
    get_settings.cache_clear()
    recipes.records_by_id.cache_clear()
