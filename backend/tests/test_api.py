import pytest
from fastapi.testclient import TestClient

from api import main
from core.llm import LLMError
from core.ratelimit import MemoryRateLimiter
from core.schemas import RecipesResponse

HEADERS = {"X-CAC-Client": "web"}
BODY = {"ingredients": [{"name": "Tomatoes", "quantity": 300, "unit": "g"}]}

FAKE_RESULT = RecipesResponse.model_validate({
    "recipes": [{"id": 1, "name": "Soup", "ingredients": ["water"], "instructions": ["Boil."]}]
})


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(main, "limiter", MemoryRateLimiter(per_ip_daily=15, per_ip_burst=5, global_daily=300))

    async def fake_generate(req):
        return FAKE_RESULT

    monkeypatch.setattr(main, "generate_recipes", fake_generate)
    return TestClient(main.app)


def test_health(client):
    res = client.get("/health")
    assert res.status_code == 200
    assert res.json() == {"status": "ok"}


def test_generate_success(client):
    res = client.post("/generate", json=BODY, headers=HEADERS)
    assert res.status_code == 200
    assert res.json() == FAKE_RESULT.model_dump(exclude_none=True)
    assert res.headers["X-RateLimit-Remaining"] == "14"
    assert res.headers["Cache-Control"] == "no-store"


def test_missing_client_header_is_forbidden(client):
    assert client.post("/generate", json=BODY).status_code == 403


def test_invalid_json(client):
    res = client.post("/generate", content=b"{nope", headers={**HEADERS, "Content-Type": "application/json"})
    assert res.status_code == 400
    assert res.json()["error"] == "Invalid JSON body"


def test_validation_error_message_is_readable(client):
    res = client.post("/generate", json={"ingredients": []}, headers=HEADERS)
    assert res.status_code == 400
    assert res.json()["error"] == "Add at least one ingredient."


def test_body_too_large(client):
    res = client.post("/generate", json={"x": "a" * 20_000}, headers=HEADERS)
    assert res.status_code == 413


def test_rate_limit(client, monkeypatch):
    monkeypatch.setattr(main, "limiter", MemoryRateLimiter(per_ip_daily=1, per_ip_burst=5, global_daily=300))
    assert client.post("/generate", json=BODY, headers=HEADERS).status_code == 200
    res = client.post("/generate", json=BODY, headers=HEADERS)
    assert res.status_code == 429
    assert res.json()["scope"] == "ip-daily"
    assert "Retry-After" in res.headers


def test_llm_failure_returns_502(client, monkeypatch):
    async def broken(req):
        raise LLMError("boom")

    monkeypatch.setattr(main, "generate_recipes", broken)
    res = client.post("/generate", json=BODY, headers=HEADERS)
    assert res.status_code == 502
    assert "boom" not in res.text  # internal details stay in the server log


def test_cors_allows_local_frontend(client):
    res = client.options(
        "/generate",
        headers={
            "Origin": "http://localhost:5173",
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "content-type,x-cac-client",
        },
    )
    assert res.status_code == 200
    assert res.headers["access-control-allow-origin"] == "http://localhost:5173"


def test_cors_blocks_other_sites(client):
    res = client.options(
        "/generate",
        headers={"Origin": "https://evil.example", "Access-Control-Request-Method": "POST"},
    )
    assert "access-control-allow-origin" not in res.headers
