import asyncio
import json

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from api import main
from core import vision
from core.ratelimit import MemoryRateLimiter
from core.schemas import DetectedIngredients
from core.vision import InvalidImageError, build_vision_messages, detect_image_type

JPEG = b"\xff\xd8\xff\xe0" + b"\x00" * 200
PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 200
WEBP = b"RIFF\x00\x00\x00\x00WEBP" + b"\x00" * 200
HEADERS = {"X-CAC-Client": "web", "Content-Type": "image/jpeg"}
FOUND = {"ingredients": [{"name": "Tomato", "quantity": 3, "unit": "pcs"}, {"name": "milk", "quantity": 1000, "unit": "ml"}]}


# ------------------------------ image checks ------------------------------


@pytest.mark.parametrize("data, mime", [(JPEG, "image/jpeg"), (PNG, "image/png"), (WEBP, "image/webp")])
def test_image_type_from_magic_bytes(data, mime):
    assert detect_image_type(data) == mime


@pytest.mark.parametrize(
    "data, message",
    [
        (b"", "empty"),
        (b"<html>" + b"x" * 200, "JPEG, PNG or WebP"),  # an HTML page renamed to .jpg
        (b"GIF89a" + b"x" * 200, "JPEG, PNG or WebP"),
        (b"\xff\xd8\xff" + b"x" * (vision.MAX_IMAGE_BYTES + 1), "too large"),
    ],
)
def test_bad_images_are_rejected(data, message):
    with pytest.raises(InvalidImageError, match=message):
        detect_image_type(data)


def test_image_is_sent_as_data_url_with_the_see_only_rule():
    messages = build_vision_messages(PNG, "image/png")
    assert messages[0]["content"].startswith("You are the Fridge Scanner.")
    text, image = messages[1]["content"]
    assert "Describe only what you can see" in text["text"]
    assert image["image_url"]["url"].startswith("data:image/png;base64,iVBORw0KGgo")


# ------------------------------ output schema ------------------------------


def test_detected_ingredients_are_cleaned():
    result = DetectedIngredients.model_validate(
        {"ingredients": [{"name": " Tomato\n", "quantity": 3, "unit": "pcs"}, {"name": "tomato", "quantity": 1, "unit": "pcs"}]}
    )
    assert [i.name for i in result.ingredients] == ["Tomato"]  # duplicates removed


@pytest.mark.parametrize(
    "item",
    [
        {"name": "milk", "quantity": 1, "unit": "litre"},  # unit not in the app's list
        {"name": "milk", "quantity": 0, "unit": "ml"},  # the app needs an amount
        {"name": "", "quantity": 1, "unit": "ml"},
    ],
)
def test_invalid_items_trigger_repair(item):
    with pytest.raises(ValidationError):
        DetectedIngredients.model_validate({"ingredients": [item]})


def test_long_lists_are_cut_to_the_app_limit():
    items = [{"name": f"food {i}", "quantity": 1, "unit": "pcs"} for i in range(30)]
    assert len(DetectedIngredients.model_validate({"ingredients": items}).ingredients) == 20


def test_detect_uses_the_vision_model(monkeypatch):
    used = {}

    async def chat(messages, **kwargs):
        used.update(kwargs)
        return json.dumps(FOUND)

    monkeypatch.setattr("core.llm.chat", chat)
    monkeypatch.setenv("VISION_MODEL", "some/vision-model")
    vision.get_settings.cache_clear()
    result = asyncio.run(vision.detect_ingredients(JPEG))
    assert used["model"] == "some/vision-model" and used["temperature"] == 0
    assert [i.name for i in result.ingredients] == ["Tomato", "milk"]


# ------------------------------ endpoint ------------------------------


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(main, "photo_limiter", MemoryRateLimiter(per_ip_daily=10, per_ip_burst=3, global_daily=150))

    async def fake_detect(data):
        return DetectedIngredients.model_validate(FOUND)

    monkeypatch.setattr(main, "detect_ingredients", fake_detect)
    return TestClient(main.app)


def test_endpoint_returns_step1_format(client):
    res = client.post("/detect-ingredients", content=JPEG, headers=HEADERS)
    assert res.status_code == 200
    assert res.json() == {"ingredients": [{"name": "Tomato", "quantity": 3.0, "unit": "pcs"}, {"name": "milk", "quantity": 1000.0, "unit": "ml"}]}
    assert res.headers["X-RateLimit-Remaining"] == "9"


def test_endpoint_rejects_non_images_before_spending_money(client, monkeypatch):
    async def must_not_run(data):
        raise AssertionError("LLM must not be called")

    monkeypatch.setattr(main, "detect_ingredients", must_not_run)
    res = client.post("/detect-ingredients", content=b"<html>" + b"x" * 300, headers=HEADERS)
    assert res.status_code == 415
    assert client.post("/detect-ingredients", content=JPEG, headers={"Content-Type": "image/jpeg"}).status_code == 403


def test_endpoint_too_large(client):
    big = b"\xff\xd8\xff" + b"x" * (vision.MAX_IMAGE_BYTES + 10)
    assert client.post("/detect-ingredients", content=big, headers=HEADERS).status_code == 413


def test_endpoint_empty_result_has_a_message(client, monkeypatch):
    async def nothing(data):
        return DetectedIngredients()

    monkeypatch.setattr(main, "detect_ingredients", nothing)
    body = client.post("/detect-ingredients", content=JPEG, headers=HEADERS).json()
    assert body["ingredients"] == [] and "No food found" in body["message"]


def test_endpoint_has_its_own_rate_limit(client, monkeypatch):
    monkeypatch.setattr(main, "photo_limiter", MemoryRateLimiter(per_ip_daily=1, per_ip_burst=5, global_daily=150))
    assert client.post("/detect-ingredients", content=JPEG, headers=HEADERS).status_code == 200
    assert client.post("/detect-ingredients", content=JPEG, headers=HEADERS).status_code == 429


def test_endpoint_llm_failure(client, monkeypatch):
    async def broken(data):
        raise RuntimeError("provider down")

    monkeypatch.setattr(main, "detect_ingredients", broken)
    res = client.post("/detect-ingredients", content=JPEG, headers=HEADERS)
    assert res.status_code == 502 and "provider" not in res.text


@pytest.mark.parametrize("name", ["food container", "bottle", "Bottles", "canned food", "glass jar", "leftovers", "unknown item", "sauce"])
def test_generic_items_are_dropped(name):
    result = DetectedIngredients.model_validate({"ingredients": [{"name": name, "quantity": 1, "unit": "pcs"}, {"name": "soy sauce", "quantity": 1, "unit": "pcs"}]})
    assert [i.name for i in vision.drop_generic_items(result).ingredients] == ["soy sauce"]
