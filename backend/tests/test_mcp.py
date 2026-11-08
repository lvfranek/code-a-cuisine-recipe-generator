"""MCP server tests through a real MCP client (in-process), with a small test index."""

import asyncio
import json

import pytest
from mcp.client.client import Client

from core.nutrition import FoodMatch, NutritionResult
from core.schemas import Nutrition
from mcp_server import server
from tests.test_nutrition import FOODS
from tests.test_retrieval import index  # noqa: F401  (fixture: temp ChromaDB with 3 recipes)


def run(coro_fn):
    async def go():
        async with Client(server.mcp) as client:
            return await coro_fn(client)

    return asyncio.run(go())


def test_tools_and_resources_are_discoverable():
    async def check(c):
        tools = {t.name: t for t in (await c.list_tools()).tools}
        resources = [str(r.uri) for r in (await c.list_resources()).resources]
        return tools, resources

    tools, resources = run(check)
    assert set(tools) == {"search_recipes", "get_recipe", "get_nutrition"}
    assert all(t.description and t.output_schema for t in tools.values())
    assert set(tools["search_recipes"].input_schema["properties"]) == {"ingredients", "diets", "cuisines", "max_minutes", "limit"}
    assert resources == ["recipes://cuisines", "recipes://diets"]


def test_search_and_get_recipe(index):  # noqa: F811
    async def check(c):
        found = await c.call_tool("search_recipes", {"ingredients": ["chicken", "rice", "onion"], "limit": 2})
        first = found.structured_content["results"][0]["itemId"]
        detail = await c.call_tool("get_recipe", {"item_id": first})
        return found, detail

    found, detail = run(check)
    assert not found.is_error
    assert found.structured_content["results"][0]["name"] == "Chicken Rice"
    assert found.structured_content["results"][0]["missing"] == []
    assert detail.structured_content["ingredients"] == ["chicken", "rice", "onion"]
    assert detail.structured_content["source"]["license"] == "CC BY-SA 4.0"


def test_filters_and_empty_result(index):  # noqa: F811
    async def check(c):
        vegan = await c.call_tool("search_recipes", {"ingredients": ["chicken"], "diets": ["Vegan"]})
        none = await c.call_tool("search_recipes", {"ingredients": ["tomato"], "cuisines": ["Thai"]})
        return vegan, none

    vegan, none = run(check)
    assert {r["itemId"] for r in vegan.structured_content["results"]} <= {"r1", "r3"}
    assert none.structured_content["count"] == 0 and "fewer filters" in none.structured_content["hint"]


@pytest.mark.parametrize(
    "tool, args, message",
    [
        ("get_recipe", {"item_id": "wb-nope"}, "Use search_recipes"),
        ("search_recipes", {"ingredients": ["x"], "diets": ["Carnivore"]}, "Unknown filter value"),
        ("search_recipes", {"ingredients": []}, "ingredients"),
        ("get_nutrition", {"items": [{"food": "rice", "grams": -5}]}, "grams"),
        ("search_recipes", {"ingredients": ["x"], "limit": 99}, "limit"),
    ],
)
def test_errors_are_explained_to_the_ai(index, tool, args, message):  # noqa: F811
    result = run(lambda c: c.call_tool(tool, args))
    assert result.is_error
    assert message in result.content[0].text


def test_missing_index_is_explained(tmp_path, monkeypatch):
    # conftest points CHROMA_DIR to an empty folder: the AI must learn how to fix it.
    result = run(lambda c: c.call_tool("search_recipes", {"ingredients": ["rice"]}))
    assert result.is_error and "build_index" in result.content[0].text


def test_nutrition_is_calculated_in_code(monkeypatch):
    monkeypatch.setattr(server, "calculate", lambda items, portions: NutritionResult(Nutrition(calories=500, protein=20), 1.0, 520))
    monkeypatch.setattr(server, "match_foods", lambda names: [FoodMatch(FOODS[n], 0.9) if n in FOODS else None for n in names])

    result = run(lambda c: c.call_tool("get_nutrition", {"items": [{"food": "rice", "grams": 200}, {"food": "unicorn", "grams": 20}], "portions": 2}))

    data = result.structured_content
    assert data["perPortion"]["calories"] == 500 and data["reliable"] is True
    assert data["items"][0]["usdaMatch"].startswith("Rice, white")
    assert data["items"][1]["usdaMatch"] is None
    assert data["source"] == "USDA FoodData Central"


def test_resources(index):  # noqa: F811
    async def check(c):
        cuisines = json.loads((await c.read_resource("recipes://cuisines")).contents[0].text)
        diets = json.loads((await c.read_resource("recipes://diets")).contents[0].text)
        return cuisines, diets

    cuisines, diets = run(check)
    assert cuisines["total"] == 3 and cuisines["cuisines"]["Italian"] == 1
    assert "Vegan" in diets["diets"] and "honey" in diets["diets"]["Vegetarian"]
