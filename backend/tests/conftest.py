import pytest

from core.config import get_settings


@pytest.fixture(autouse=True)
def fake_settings(monkeypatch):
    """Tests never use the real key from backend/.env and never call OpenRouter."""
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
    monkeypatch.setenv("MAX_REPAIR_ATTEMPTS", "5")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()
