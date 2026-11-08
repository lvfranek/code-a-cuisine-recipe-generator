"""Workflow tests. The LLM is faked per agent (recognized by its system prompt)."""

import asyncio
import json

import pytest

from core import generate
from core.agents import graph
from core.agents.graph import WorkflowError, generate_recipes
from core.config import get_settings
from core.retrieval import IndexNotReadyError
from core.schemas import GenerateRequest
from tests.test_generate import HITS

REQUEST = GenerateRequest.model_validate({
    "ingredients": [{"name": "Kartoffeln"}, {"name": "Tomaten"}],
    "portions": 3,
    "dietPreferences": ["Vegan"],
})


def recipe(name, based_on=None):
    r = {
        "name": name,
        "description": "Nice.",
        "cookTime": "20 min",
        "cuisine": "Other",
        "dietTags": ["Vegan"],
        "portions": 1,
        "nutrition": {"calories": 300, "protein": 8, "carbs": 40, "fat": 9},
        "ingredients": ["2 potatoes"],
        "instructions": ["Boil.", "Serve."],
    }
    if based_on:
        r["basedOnId"] = based_on
    return r


INPUT_OK = json.dumps({"ingredients": ["potato", "tomato"]})
ADAPT_OK = json.dumps({"recipes": [recipe("A", "wb-1"), recipe("B", "wb-2"), recipe("C", "wb-3")]})
CREATE_OK = json.dumps({"recipes": [recipe("Free 1"), recipe("Free 2"), recipe("Free 3")]})


def fake_llm(monkeypatch, input_answer=INPUT_OK, adapt_answer=ADAPT_OK, create_answer=CREATE_OK):
    """Answer by agent/task. Returns the list of task names that were called."""
    calls = []

    async def chat(messages, **kwargs):
        system, user = messages[0]["content"], messages[-1]["content"]
        if "Ingredient Analyst" in system:
            calls.append("input")
            return input_answer
        if "repair invalid JSON" in system:
            calls.append("repair")
            return "still broken"
        if "Pick the" in user:
            calls.append("adapt")
            return adapt_answer
        calls.append("create")
        return create_answer

    monkeypatch.setattr("core.llm.chat", chat)
    monkeypatch.setenv("MAX_REPAIR_ATTEMPTS", "1")  # keep failure tests short
    get_settings.cache_clear()
    return calls


def fake_search(monkeypatch, result=HITS):
    used_terms = []

    def search(names, filters, k):
        used_terms.append(names)
        if isinstance(result, Exception):
            raise result
        return result

    monkeypatch.setattr(generate, "search_recipes", search)
    return used_terms


def run():
    return asyncio.run(graph.workflow.ainvoke({"request": REQUEST, "errors": []}))


def test_graph_has_expected_nodes():
    nodes = set(graph.workflow.get_graph().nodes)
    assert {"input_agent", "retriever", "chef_agent", "fallback_chef", "final"} <= nodes


def test_happy_path_uses_normalized_terms_and_real_recipes(monkeypatch):
    calls = fake_llm(monkeypatch)
    used_terms = fake_search(monkeypatch)

    state = run()

    assert calls == ["input", "adapt"]
    assert used_terms[0] == ["potato", "tomato"]  # German input translated for the search
    assert state["errors"] == []
    assert state["workflow_step"] == "final"
    assert [r.basedOn.itemId for r in state["result"].recipes] == ["wb-1", "wb-2", "wb-3"]
    assert all(r.portions == 3 for r in state["result"].recipes)


def test_input_agent_failure_falls_back_to_raw_names(monkeypatch):
    calls = fake_llm(monkeypatch, input_answer="not json")
    used_terms = fake_search(monkeypatch)

    state = run()

    assert used_terms[0] == ["Kartoffeln", "Tomaten"]
    assert any(e.startswith("input_agent:") for e in state["errors"])
    assert state["result"].recipes[0].basedOn is not None
    assert "adapt" in calls


@pytest.mark.parametrize("search_result", [[], IndexNotReadyError("no index")])
def test_no_candidates_uses_fallback_chef(monkeypatch, search_result):
    calls = fake_llm(monkeypatch)
    fake_search(monkeypatch, search_result)

    state = run()

    assert calls[-1] == "create"
    assert [r.name for r in state["result"].recipes] == ["Free 1", "Free 2", "Free 3"]
    assert all(r.basedOn is None for r in state["result"].recipes)


def test_chef_failure_uses_fallback_chef(monkeypatch):
    calls = fake_llm(monkeypatch, adapt_answer="broken")
    fake_search(monkeypatch)

    state = run()

    assert "adapt" in calls and calls[-1] == "create"
    assert any(e.startswith("chef_agent:") for e in state["errors"])
    assert state["result"].recipes[0].name == "Free 1"


def test_everything_fails_raises_workflow_error(monkeypatch):
    fake_llm(monkeypatch, adapt_answer="broken", create_answer="broken")
    fake_search(monkeypatch)

    with pytest.raises(WorkflowError, match="fallback_chef"):
        asyncio.run(generate_recipes(REQUEST))
