import json

import pytest
from pydantic import ValidationError

from core import generate
from core.agents.config import AGENTS, TASKS, build_messages, build_task_prompt
from core.generate import (
    adapted_schema,
    candidates_context,
    filter_steps,
    request_context,
    retrieve_candidates,
)
from core.retrieval import SearchHit
from core.schemas import GenerateRequest, IngredientTerms, RecipeRecord

REQUEST = GenerateRequest.model_validate({
    "ingredients": [{"name": "Tomatoes", "quantity": 300, "unit": "g"}, {"name": "Basil"}],
    "portions": 4,
    "cookingTime": "quick",
    "cuisines": ["Any", "Italian"],
    "dietPreferences": ["Vegan"],
})


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


# --------------------------- agent config ---------------------------


def test_every_agent_and_task_is_complete():
    for agent in AGENTS.values():
        assert agent["role"] and agent["goal"] and agent["backstory"]
    for task in TASKS.values():
        assert task["description"] and task["expected_output"] and task["agent"] in AGENTS


def test_messages_use_the_task_agent():
    messages = build_messages("normalize_ingredients", "Ingredient list:\n- Kartoffeln")
    assert messages[0]["content"].startswith("You are the Ingredient Analyst.")
    assert "- Kartoffeln" in messages[1]["content"]
    assert '{"ingredients":' in messages[1]["content"]  # JSON braces survive placeholder filling


def test_task_prompt_fills_placeholders():
    prompt = build_task_prompt("adapt_recipes", "ctx", count=3, example='{"name": "X"}')
    assert "Pick the 3 best candidates" in prompt
    assert "exactly 3 recipes" in prompt and '{"name": "X"}' in prompt
    assert "{count}" not in prompt and "{example}" not in prompt


# ------------------------------ context ------------------------------


def test_request_context_contains_user_input():
    ctx = request_context(REQUEST)
    assert "- Tomatoes (300g)" in ctx and "- Basil" in ctx
    assert "Portions per recipe: 4" in ctx
    assert "about 15 minutes" in ctx
    assert "Preferred cuisines: Italian" in ctx
    assert "Dietary requirements (must respect all): Vegan" in ctx


def test_candidates_context_contains_ids_and_matches():
    ctx = candidates_context(HITS)
    assert "[wb-1] Tomato Salad" in ctx and "[wb-3] Pomodoro" in ctx
    assert "Ingredients: 2 tomatoes; basil leaves" in ctx
    assert "User already has: tomato, basil" in ctx


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


def test_retrieve_uses_search_terms(monkeypatch):
    used = []
    monkeypatch.setattr(generate, "search_recipes", lambda names, filters, k: used.append(names) or HITS)
    retrieve_candidates(REQUEST, ["tomato", "basil"])
    assert used[0] == ["tomato", "basil"]


# ------------------------------ schemas ------------------------------


def draft(name, based_on):
    return {"name": name, "ingredients": ["x"], "instructions": ["y"], "basedOnId": based_on}


def test_adapted_schema_only_accepts_real_ids_once():
    schema = adapted_schema(["wb-1", "wb-2"])
    schema.model_validate({"recipes": [draft("A", "wb-1"), draft("B", "wb-2")]})
    with pytest.raises(ValidationError):
        schema.model_validate({"recipes": [draft("A", "wb-999")]})
    with pytest.raises(ValidationError, match="unique"):
        schema.model_validate({"recipes": [draft("A", "wb-1"), draft("B", "wb-1")]})


def test_ingredient_terms_are_cleaned():
    terms = IngredientTerms.model_validate({"ingredients": ["Potato", " potato ", "", "Chicken\nBreast"]})
    assert terms.ingredients == ["potato", "chicken breast"]
    with pytest.raises(ValidationError):
        IngredientTerms.model_validate({"ingredients": [" "]})
    assert json.loads(IngredientTerms(ingredients=["a"]).model_dump_json()) == {"ingredients": ["a"]}


def test_dishes_are_preferred_over_basics(monkeypatch):
    basics = [hit("wb-s", "Tomato Sauce"), hit("wb-d", "Basil Dressing")]
    monkeypatch.setattr(generate, "search_recipes", lambda names, filters, k: basics + HITS)
    picked = retrieve_candidates(REQUEST)
    assert [h.record.itemId for h in picked] == ["wb-1", "wb-2", "wb-3"]


def test_basics_fill_up_when_dishes_are_rare(monkeypatch):
    basics = [hit("wb-s", "Tomato Sauce")]
    monkeypatch.setattr(generate, "search_recipes", lambda names, filters, k: basics + HITS[:1])
    picked = retrieve_candidates(REQUEST)
    assert [h.record.itemId for h in picked] == ["wb-1", "wb-s"]
