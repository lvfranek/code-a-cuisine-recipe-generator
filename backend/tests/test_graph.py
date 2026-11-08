"""Workflow tests. The LLM is faked per agent (recognized by its system prompt),
USDA lookups are faked too, so the tests run offline and fast."""

import asyncio
import json

import pytest

from core import generate
from core.agents import graph
from core.agents.graph import WorkflowError, check_rules, extra_ingredients, generate_recipes
from core.config import get_settings
from core.nutrition import NutritionResult
from core.retrieval import IndexNotReadyError
from core.schemas import GenerateRequest, Nutrition, RecipesResponse
from tests.test_generate import HITS

REQUEST = GenerateRequest.model_validate({
    "ingredients": [{"name": "Kartoffeln"}, {"name": "Tomaten"}],
    "portions": 3,
    "dietPreferences": ["Vegan"],
})


def recipe(name, based_on=None, ingredients=("2 potatoes", "3 tomatoes"), tags=("Vegan",)):
    r = {
        "name": name,
        "description": "Nice.",
        "cookTime": "20 min",
        "cuisine": "Other",
        "dietTags": list(tags),
        "portions": 1,
        "nutrition": {"calories": 999, "protein": 8, "carbs": 40, "fat": 9},
        "ingredients": list(ingredients),
        "instructions": ["Boil.", "Serve."],
    }
    if based_on:
        r["basedOnId"] = based_on
    return r


def answer(*recipes):
    return json.dumps({"recipes": list(recipes)})


INPUT_OK = json.dumps({"ingredients": ["potato", "tomato"]})
ADAPT_OK = answer(recipe("A", "wb-1"), recipe("B", "wb-2"), recipe("C", "wb-3"))
CREATE_OK = answer(recipe("Free 1"), recipe("Free 2"), recipe("Free 3"))
CRITIC_OK = json.dumps({"recipes": [{"index": i, "problems": []} for i in (1, 2, 3)]})
WEIGHTS_OK = json.dumps({"recipes": [{"index": i, "items": [{"food": "potato", "grams": 300}]} for i in (1, 2, 3)]})


def fake_llm(monkeypatch, *, input_answer=INPUT_OK, adapt=(ADAPT_OK,), create=(CREATE_OK,), critic=(CRITIC_OK,), weights=WEIGHTS_OK):
    """Answer by agent/task; adapt/create/critic answer in order per call (last one repeats)."""
    calls = []
    queues = {"adapt": list(adapt), "create": list(create), "critic": list(critic)}

    def next_answer(kind):
        q = queues[kind]
        return q.pop(0) if len(q) > 1 else q[0]

    async def chat(messages, **kwargs):
        system, user = messages[0]["content"], messages[-1]["content"]
        if "Ingredient Analyst" in system:
            calls.append("input")
            return input_answer
        if "Diet Inspector" in system:
            calls.append("critic")
            return next_answer("critic")
        if "Nutrition Analyst" in system:
            calls.append("weights")
            return weights
        if "repair invalid JSON" in system:
            calls.append("repair")
            return "still broken"
        if "Pick the" in user:
            calls.append("adapt")
            return next_answer("adapt")
        calls.append("create")
        return next_answer("create")

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


@pytest.fixture(autouse=True)
def fake_usda(monkeypatch):
    """300 g potato for 3 portions -> pretend USDA says 77 kcal per portion."""

    def calc(items, portions):
        return NutritionResult(Nutrition(calories=77, protein=2, carbs=17, fat=0.1), coverage=1.0, total_grams=300)

    monkeypatch.setattr(graph, "calculate", calc)


def run():
    return asyncio.run(graph.workflow.ainvoke({"request": REQUEST, "errors": [], "steps": []}))


# ------------------------------ structure ------------------------------


def test_graph_has_expected_nodes():
    nodes = set(graph.workflow.get_graph().nodes)
    assert {"input_agent", "retriever", "chef_agent", "fallback_chef", "diet_checker", "nutrition_agent", "review", "final"} <= nodes


# ------------------------------ happy path ------------------------------


def test_happy_path(monkeypatch):
    calls = fake_llm(monkeypatch)
    used_terms = fake_search(monkeypatch)

    state = run()

    assert used_terms[0] == ["potato", "tomato"]  # German input translated for the search
    assert sorted(calls) == sorted(["input", "adapt", "critic", "weights"])
    assert state["errors"] == []
    assert state["steps"][:3] == ["input_agent", "retriever", "chef_agent"]
    assert set(state["steps"][3:5]) == {"diet_checker", "nutrition_agent"}  # parallel
    assert state["steps"][5:] == ["review", "final"]
    recipes = state["final_result"].recipes
    assert [r.basedOn.itemId for r in recipes] == ["wb-1", "wb-2", "wb-3"]
    assert all(r.nutrition.calories == 77 and r.nutritionSource == "USDA" for r in recipes)
    assert all(r.portions == 3 for r in recipes)


# --------------------------- diet revisions ---------------------------


def test_rule_violation_sends_recipes_back_to_the_chef(monkeypatch):
    bad = answer(recipe("A", "wb-1", ingredients=("2 potatoes", "2 eggs")), recipe("B", "wb-2"), recipe("C", "wb-3"))
    calls = fake_llm(monkeypatch, adapt=(bad, ADAPT_OK))
    fake_search(monkeypatch)

    state = run()

    assert calls.count("adapt") == 2
    assert state["revisions"] == 1
    assert "eggs" in state["feedback"][0] if state.get("feedback") else True
    assert "Vegan" in state["final_result"].recipes[0].dietTags  # fixed in round 2


def test_critic_problem_sends_recipes_back(monkeypatch):
    critic_bad = json.dumps({"recipes": [{"index": 2, "problems": [{"diet": "Vegan", "issue": "Worcestershire contains anchovy"}]}]})
    calls = fake_llm(monkeypatch, critic=(critic_bad, CRITIC_OK))
    fake_search(monkeypatch)

    state = run()

    assert calls.count("adapt") == 2 and calls.count("critic") == 2
    assert state["revisions"] == 1


def test_gives_up_after_two_revisions_and_removes_the_tag(monkeypatch):
    bad = answer(recipe("A", "wb-1", ingredients=("2 potatoes", "1 tbsp honey")), recipe("B", "wb-2"), recipe("C", "wb-3"))
    calls = fake_llm(monkeypatch, adapt=(bad,))
    fake_search(monkeypatch)

    state = run()

    assert calls.count("adapt") == 3  # first try + 2 revisions
    assert state["revisions"] == 2
    recipes = state["final_result"].recipes
    assert "Vegan" not in recipes[0].dietTags  # never claim a diet we know is broken
    assert "Vegan" in recipes[1].dietTags


def test_wrongly_claimed_tag_is_removed_without_revision(monkeypatch):
    # Not a required diet -> no revision, but the false tag must go.
    tagged = answer(recipe("A", "wb-1", ingredients=("200 g spaghetti", "3 tomatoes"), tags=("Vegan", "Gluten-Free")), recipe("B", "wb-2"), recipe("C", "wb-3"))
    calls = fake_llm(monkeypatch, adapt=(tagged,))
    fake_search(monkeypatch)

    state = run()

    assert calls.count("adapt") == 1
    assert state["final_result"].recipes[0].dietTags == ["Vegan"]


# ------------------------------ nutrition ------------------------------


def test_unreliable_nutrition_keeps_the_estimate(monkeypatch):
    fake_llm(monkeypatch)
    fake_search(monkeypatch)
    monkeypatch.setattr(graph, "calculate", lambda items, portions: NutritionResult(Nutrition(calories=1), coverage=0.3, total_grams=300))

    recipes = run()["final_result"].recipes

    assert all(r.nutrition.calories == 999 and r.nutritionSource == "estimate" for r in recipes)


def test_nutrition_agent_failure_still_returns_recipes(monkeypatch):
    fake_llm(monkeypatch, weights="broken")
    fake_search(monkeypatch)

    state = run()

    assert any(e.startswith("nutrition_agent:") for e in state["errors"])
    assert all(r.nutritionSource == "estimate" for r in state["final_result"].recipes)


# ------------------------------ fallbacks ------------------------------


def test_input_agent_failure_falls_back_to_raw_names(monkeypatch):
    fake_llm(monkeypatch, input_answer="not json")
    used_terms = fake_search(monkeypatch)

    state = run()

    assert used_terms[0] == ["Kartoffeln", "Tomaten"]
    assert any(e.startswith("input_agent:") for e in state["errors"])
    assert state["final_result"].recipes[0].basedOn is not None


@pytest.mark.parametrize("search_result", [[], IndexNotReadyError("no index")])
def test_no_candidates_uses_fallback_chef(monkeypatch, search_result):
    calls = fake_llm(monkeypatch)
    fake_search(monkeypatch, search_result)

    state = run()

    assert "create" in calls and "adapt" not in calls
    assert [r.name for r in state["final_result"].recipes] == ["Free 1", "Free 2", "Free 3"]
    assert all(r.basedOn is None for r in state["final_result"].recipes)
    assert "diet_checker" in state["steps"]  # free recipes are checked too


def test_chef_failure_uses_fallback_chef(monkeypatch):
    calls = fake_llm(monkeypatch, adapt=("broken",))
    fake_search(monkeypatch)

    state = run()

    assert "adapt" in calls and "create" in calls
    assert any(e.startswith("chef_agent:") for e in state["errors"])
    assert state["final_result"].recipes[0].name == "Free 1"


def test_everything_fails_raises_workflow_error(monkeypatch):
    fake_llm(monkeypatch, adapt=("broken",), create=("broken",))
    fake_search(monkeypatch)

    with pytest.raises(WorkflowError, match="fallback_chef"):
        asyncio.run(generate_recipes(REQUEST))


# ------------------------------ rule helpers ------------------------------


def test_extra_ingredients():
    lines = ["2 potatoes", "1 tbsp olive oil", "salt and pepper", "1 tsp paprika", "200 g salmon", "1 cup cream"]
    assert extra_ingredients(lines, ["potato"]) == ["200 g salmon", "1 cup cream"]


def test_check_rules_flags_too_many_extras():
    result = RecipesResponse.model_validate({"recipes": [
        {"id": 1, "name": "X", "ingredients": ["2 potatoes", "salmon", "cream", "dill", "capers"], "instructions": ["a"]}
    ]})
    report = check_rules(result, [], ["potato"])
    assert report.problems[1][0][0] == "extra"


# ------------------------------ streaming ------------------------------


def collect(req=REQUEST):
    async def go():
        return [e async for e in graph.stream_recipes(req)]

    return asyncio.run(go())


def test_stream_reports_every_step_and_the_result(monkeypatch):
    fake_llm(monkeypatch)
    fake_search(monkeypatch)

    events = collect()

    steps = [d["step"] for e, d in events if e == "step"]
    assert steps[:3] == ["input_agent", "retriever", "chef_agent"]
    assert set(steps[3:5]) == {"diet_checker", "nutrition_agent"}
    assert steps[5:] == ["review", "final"]
    assert events[-1][0] == "result"
    assert events[-1][1]["recipes"][0]["nutritionSource"] == "USDA"


def test_stream_reports_revisions_and_failures(monkeypatch):
    bad = answer(recipe("A", "wb-1", ingredients=("2 potatoes", "2 eggs")), recipe("B", "wb-2"), recipe("C", "wb-3"))
    fake_llm(monkeypatch, input_answer="broken", adapt=(bad, ADAPT_OK))
    fake_search(monkeypatch)

    events = collect()

    assert ("step", {"step": "input_agent", "status": "failed"}) in events
    assert ("revision", {"round": 1, "problems": 1}) in events
    assert events[-1][0] == "result"


def test_stream_raises_when_nothing_works(monkeypatch):
    fake_llm(monkeypatch, adapt=("broken",), create=("broken",))
    fake_search(monkeypatch)

    with pytest.raises(WorkflowError):
        collect()


def test_false_critic_alarm_does_not_cause_a_revision(monkeypatch):
    critic_wrong = json.dumps({"recipes": [{"index": 1, "problems": [{"diet": "Vegetarian", "issue": "contains honey"}]}]})
    fake_search(monkeypatch)
    req = REQUEST.model_copy(update={"dietPreferences": ["Vegetarian"]})
    tagged = answer(recipe("A", "wb-1", tags=("Vegetarian",)), recipe("B", "wb-2"), recipe("C", "wb-3"))
    calls = fake_llm(monkeypatch, adapt=(tagged,), critic=(critic_wrong,))

    state = asyncio.run(graph.workflow.ainvoke({"request": req, "errors": [], "steps": []}))

    assert calls.count("adapt") == 1
    assert "Vegetarian" in state["final_result"].recipes[0].dietTags


def test_misleading_name_breaks_the_diet_too(monkeypatch):
    named = answer(recipe("Chicken Salad Sandwich", "wb-1", ingredients=("2 slices bread", "3 tomatoes"), tags=("Vegetarian",)), recipe("B", "wb-2"), recipe("C", "wb-3"))
    calls = fake_llm(monkeypatch, adapt=(named, ADAPT_OK))
    fake_search(monkeypatch)
    req = REQUEST.model_copy(update={"dietPreferences": ["Vegetarian"]})

    state = asyncio.run(graph.workflow.ainvoke({"request": req, "errors": [], "steps": []}))

    assert calls.count("adapt") == 2  # sent back to the chef
    assert state["final_result"].recipes[0].name == "A"
