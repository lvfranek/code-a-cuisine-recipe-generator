import asyncio
import json

import pytest

from core import generate
from core.generate import (
    build_prompt,
    build_rag_prompt,
    filter_steps,
    generate_recipes,
    retrieve_candidates,
)
from core.retrieval import IndexNotReadyError, SearchHit
from core.schemas import GenerateRequest, RecipeRecord

REQUEST = GenerateRequest.model_validate({
    "ingredients": [{"name": "Tomatoes", "quantity": 300, "unit": "g"}, {"name": "Basil"}],
    "portions": 4,
    "cookingTime": "quick",
    "cuisines": ["Any", "Italian"],
    "dietPreferences": ["Vegan"],
})


def draft(name, based_on=None):
    d = {
        "name": name,
        "description": "Nice.",
        "cookTime": "15 min",
        "cuisine": "Italian",
        "dietTags": ["Vegan"],
        "portions": 1,  # wrong on purpose: must be replaced by the requested 4
        "nutrition": {"calories": 300, "protein": 8, "carbs": 40, "fat": 9},
        "ingredients": ["300 g tomatoes"],
        "instructions": ["Chop.", "Serve."],
    }
    if based_on:
        d["basedOnId"] = based_on
    return d


def hit(item_id, name="Tomato Salad"):
    record = RecipeRecord.model_validate({
        "itemId": item_id,
        "name": name,
        "description": "Fresh.",
        "cuisine": "Italian",
        "dietTags": ["Vegan"],
        "cookTimeMinutes": 10,
        "servings": 2,
        "ingredients": [{"text": "2 tomatoes", "name": "tomato"}, {"text": "basil leaves", "name": "basil"}],
        "instructions": ["Slice the tomatoes.", "Add basil."],
        "category": "Salad",
        "source": {"name": "Wikibooks Cookbook", "url": f"https://wb/{item_id}", "license": "CC BY-SA 4.0"},
    })
    return SearchHit(record, similarity=0.8, coverage=1.0, matched=["tomato", "basil"], missing=[])


HITS = [hit("wb-1", "Tomato Salad"), hit("wb-2", "Bruschetta"), hit("wb-3", "Pomodoro")]


def fake_chat(answers, calls=None):
    """Returns the answers in order (the last one repeats). Records calls if a list is given."""
    calls = [] if calls is None else calls

    async def _chat(messages, **kwargs):
        calls.append(messages)
        return answers[min(len(calls), len(answers)) - 1]

    return _chat


# ------------------------------ prompts ------------------------------


def test_free_prompt_contains_user_input():
    prompt = build_prompt(REQUEST)
    assert "- Tomatoes (300g)" in prompt
    assert "- Basil\n" in prompt
    assert "Portions per recipe: 4" in prompt
    assert "about 15 minutes" in prompt
    assert "Preferred cuisines: Italian" in prompt
    assert "Dietary requirements (must respect all): Vegan" in prompt


def test_rag_prompt_contains_candidates_and_ids():
    prompt = build_rag_prompt(REQUEST, HITS, 3)
    assert "[wb-1] Tomato Salad" in prompt and "[wb-3] Pomodoro" in prompt
    assert "Ingredients: 2 tomatoes; basil leaves" in prompt
    assert "User already has: tomato, basil" in prompt
    assert '"basedOnId": "wb-1"' in prompt


# ----------------------------- retrieval -----------------------------


def test_filters_relax_step_by_step():
    wheres = [f.to_where() for f in filter_steps(REQUEST)]
    assert wheres == [
        {"$and": [{"diet_vegan": True}, {"cuisine": {"$in": ["Italian"]}}, {"cookTimeMinutes": {"$lte": 25}}]},
        {"$and": [{"diet_vegan": True}, {"cookTimeMinutes": {"$lte": 25}}]},
        {"diet_vegan": True},
        None,
    ]


def test_retrieve_relaxes_until_enough(monkeypatch):
    seen = []

    def fake_search(names, filters, k):
        seen.append(filters.to_where())
        return HITS[:1] if len(seen) < 3 else HITS  # strict filters find too little

    monkeypatch.setattr(generate, "search_recipes", fake_search)
    assert retrieve_candidates(REQUEST) == HITS
    assert len(seen) == 3


# ----------------------------- generation -----------------------------


def test_rag_generation_adds_real_source(monkeypatch):
    monkeypatch.setattr(generate, "search_recipes", lambda names, filters, k: HITS)
    answer = json.dumps({"recipes": [draft("A", "wb-2"), draft("B", "wb-1"), draft("C", "wb-3")]})
    monkeypatch.setattr("core.llm.chat", fake_chat([answer]))

    result = asyncio.run(generate_recipes(REQUEST))

    assert [r.id for r in result.recipes] == [1, 2, 3]
    assert all(r.portions == 4 for r in result.recipes)
    first = result.recipes[0].basedOn
    assert first.name == "Bruschetta" and first.url == "https://wb/wb-2"  # from the database, not the LLM
    assert first.license == "CC BY-SA 4.0"


def test_invented_source_id_is_repaired(monkeypatch):
    monkeypatch.setattr(generate, "search_recipes", lambda names, filters, k: HITS)
    bad = json.dumps({"recipes": [draft("A", "wb-999")]})
    good = json.dumps({"recipes": [draft("A", "wb-1")]})
    calls = []
    monkeypatch.setattr("core.llm.chat", fake_chat([bad, good], calls))

    result = asyncio.run(generate_recipes(REQUEST))

    assert len(calls) == 2  # original + one repair
    assert result.recipes[0].basedOn.itemId == "wb-1"


@pytest.mark.parametrize("problem", ["no-index", "no-hits"])
def test_falls_back_to_free_generation(monkeypatch, problem):
    def fake_search(names, filters, k):
        if problem == "no-index":
            raise IndexNotReadyError("missing")
        return []

    monkeypatch.setattr(generate, "search_recipes", fake_search)
    answer = json.dumps({"recipes": [draft(f"R{i}") for i in range(4)]})
    monkeypatch.setattr("core.llm.chat", fake_chat([answer]))

    result = asyncio.run(generate_recipes(REQUEST))

    assert [r.id for r in result.recipes] == [1, 2, 3]
    assert all(r.basedOn is None for r in result.recipes)
    assert generate.RECIPE_COUNT == 3


def test_same_template_twice_is_repaired(monkeypatch):
    monkeypatch.setattr(generate, "search_recipes", lambda names, filters, k: HITS)
    twice = json.dumps({"recipes": [draft("A", "wb-1"), draft("B", "wb-1")]})
    fixed = json.dumps({"recipes": [draft("A", "wb-1"), draft("B", "wb-2")]})
    calls = []
    monkeypatch.setattr("core.llm.chat", fake_chat([twice, fixed], calls))

    result = asyncio.run(generate_recipes(REQUEST))

    assert len(calls) == 2
    assert [r.basedOn.itemId for r in result.recipes] == ["wb-1", "wb-2"]
