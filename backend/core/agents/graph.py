"""Recipe workflow as a LangGraph graph.

    START -> input_agent -> retriever -+-(candidates)-> chef_agent ----+
                                       |                  |(failed)    |
                                       +-(none)--------> fallback_chef-+
                                                                       v
                                         +--> diet_checker ----+    (parallel)
                                         +--> nutrition_agent -+
                                                               v
                                    review --(diet problems, max 2 rounds)--> back to the chef
                                       |
                                       +--(ok)--> final -> END

- Shared state (`RecipeState`): every node reads it and returns only its own fields.
- Every node is wrapped by `@node`: errors are stored in `errors` instead of
  crashing the workflow, and `workflow_step` / `steps` track progress.
- Only the retriever touches the recipe database.
- Nutrition is calculated in code from USDA data (core/nutrition.py).
"""

import asyncio
import logging
import operator
import time
from dataclasses import dataclass, field
from functools import wraps
from typing import Annotated, TypedDict

from langgraph.graph import END, START, StateGraph

from core import diet_rules
from core.agents.config import DIET_DEFINITIONS, build_messages
from core.generate import (
    RECIPE_COUNT,
    adapted_schema,
    candidates_context,
    diets,
    example_json,
    request_context,
    retrieve_candidates,
    to_rag_response,
    to_response,
)
from core.llm import complete_json
from core.nutrition import NutritionResult, calculate
from core.retrieval import PANTRY_STAPLES, SearchHit, normalize_name
from core.schemas import (
    DIET_VALUES,
    DietCritique,
    GenerateRequest,
    IngredientTerms,
    IngredientWeights,
    RecipeDrafts,
    RecipesResponse,
)

log = logging.getLogger(__name__)

MAX_REVISIONS = 2
MAX_EXTRA_INGREDIENTS = 3  # more than this = "uses too much the user does not have"

# Assumed to be at home in addition to PANTRY_STAPLES (not counted as extras).
KITCHEN_BASICS = {
    "garlic", "vinegar", "spice", "spices", "seasoning", "herb", "herbs", "paprika", "cumin", "oregano",
    "thyme", "basil", "cinnamon", "chili", "chilli", "curry", "turmeric", "coriander", "nutmeg", "bay",
    "parsley", "broth", "stock", "bouillon", "baking", "vanilla", "mustard", "ketchup", "honey",
    "lemon", "lime", "soy", "cornstarch", "yeast", "ginger",
}


class WorkflowError(RuntimeError):
    """The workflow finished without recipes."""


@dataclass
class DietReport:
    problems: dict[int, list[tuple[str, str]]] = field(default_factory=dict)  # recipe index -> (diet|"extra", text)
    wrong_tags: dict[int, set[str]] = field(default_factory=dict)  # claimed tags that the rules disprove

    def add(self, index: int, kind: str, text: str) -> None:
        self.problems.setdefault(index, []).append((kind, text))


def _last(_old, new):
    return new


class RecipeState(TypedDict, total=False):
    request: GenerateRequest  # input (validated)
    search_terms: list[str]  # input_agent
    candidates: list[SearchHit]  # retriever
    result: RecipesResponse  # chef_agent / fallback_chef
    chef: str  # which chef produced `result` (for revisions)
    diet_report: DietReport  # diet_checker
    nutrition: dict[int, NutritionResult]  # nutrition_agent, by recipe index (1-based)
    feedback: list[str]  # review -> chef
    revisions: int  # review
    final_result: RecipesResponse  # final
    workflow_step: Annotated[str, _last]  # last finished step (parallel nodes may both write)
    steps: Annotated[list[str], operator.add]  # history of finished steps
    errors: Annotated[list[str], operator.add]  # every node may append


def node(name: str):
    """Wrap a node: timing log, workflow_step/steps, and errors stored instead of raised."""

    def decorator(fn):
        @wraps(fn)
        async def wrapper(state: RecipeState) -> dict:
            start = time.perf_counter()
            try:
                update = await fn(state)
            except Exception as err:
                log.warning("%s failed after %.1fs: %s", name, time.perf_counter() - start, str(err)[:300])
                return {
                    "errors": [f"{name}: {str(err)[:300]}"],
                    "workflow_step": f"{name}_failed",
                    "steps": [f"{name}_failed"],
                }
            log.info("%s done in %.1fs", name, time.perf_counter() - start)
            return {**update, "workflow_step": name, "steps": [name]}

        return wrapper

    return decorator


def _terms_context(state: RecipeState) -> str:
    terms = state.get("search_terms")
    return f"\nEnglish search terms for the user's ingredients: {', '.join(terms)}" if terms else ""


def _feedback_context(state: RecipeState) -> str:
    feedback = state.get("feedback") or []
    if not feedback:
        return ""
    lines = "\n".join(f"- {f}" for f in feedback)
    return (
        "\n\nIMPORTANT: your previous recipes had these problems. Fix them and return ALL recipes again "
        f"(keep recipes without problems as they were):\n{lines}"
    )


def _recipes_context(result: RecipesResponse) -> str:
    return "\n\n".join(
        f"Recipe {i}: {r.name} (serves {r.portions})\n" + "\n".join(f"- {line}" for line in r.ingredients)
        for i, r in enumerate(result.recipes, start=1)
    )


# --------------------------------------------------------------------------
# Nodes: input, retrieval, chefs
# --------------------------------------------------------------------------


@node("input_agent")
async def input_agent(state: RecipeState) -> dict:
    """Clean English search terms from the user's ingredients (any language)."""
    names = "\n".join(f"- {i.name}" for i in state["request"].ingredients)
    terms = await complete_json(
        build_messages("normalize_ingredients", f"Ingredient list:\n{names}"),
        IngredientTerms,
        temperature=0,
    )
    return {"search_terms": terms.ingredients}


@node("retriever")
async def retriever(state: RecipeState) -> dict:
    """The only node with database access. Falls back to the raw names if input_agent failed."""
    req = state["request"]
    terms = state.get("search_terms") or [i.name for i in req.ingredients]
    hits = await asyncio.to_thread(retrieve_candidates, req, terms)  # CPU work off the event loop
    return {"candidates": hits}


@node("chef_agent")
async def chef_agent(state: RecipeState) -> dict:
    """Adapt the best real recipes to the user's ingredients, diet and portions."""
    req, hits = state["request"], state["candidates"]
    count = min(RECIPE_COUNT, len(hits))
    messages = build_messages(
        "adapt_recipes",
        f"{request_context(req)}{_terms_context(state)}\n\n{candidates_context(hits)}{_feedback_context(state)}",
        count=count,
        example=example_json(req.portions, hits[0].record.itemId),
    )
    adapted = await complete_json(messages, adapted_schema([h.record.itemId for h in hits]))
    return {"result": to_rag_response(adapted, hits, req.portions), "chef": "chef_agent"}


@node("fallback_chef")
async def fallback_chef(state: RecipeState) -> dict:
    """Free generation when there are no candidates or the chef failed."""
    req = state["request"]
    messages = build_messages(
        "create_recipes",
        request_context(req) + _terms_context(state) + _feedback_context(state),
        count=RECIPE_COUNT,
        example=example_json(req.portions),
    )
    drafts = await complete_json(messages, RecipeDrafts)
    return {"result": to_response(drafts, req.portions), "chef": "fallback_chef"}


# --------------------------------------------------------------------------
# Nodes: quality (run in parallel)
# --------------------------------------------------------------------------


def extra_ingredients(lines: list[str], user_terms: list[str]) -> list[str]:
    """Ingredient lines that are neither the user's ingredients nor kitchen basics."""
    have = {w for t in user_terms for w in normalize_name(t).split()}
    basics = {w for s in PANTRY_STAPLES for w in s.split()} | KITCHEN_BASICS
    extras = []
    for line in lines:
        words = set(normalize_name(line).split())
        if not words & have and not words & basics:
            extras.append(line)
    return extras


def check_rules(result: RecipesResponse, required: list[str], user_terms: list[str]) -> DietReport:
    """Code rules: required diets, wrongly claimed diet tags, too many extra ingredients."""
    report = DietReport()
    for i, recipe in enumerate(result.recipes, start=1):
        for diet in required:
            for v in diet_rules.violations(recipe.ingredients, diet):
                report.add(i, diet, f"breaks {diet}: {v}")
        wrong = {t for t in recipe.dietTags if t in DIET_VALUES and diet_rules.violations(recipe.ingredients, t)}
        if wrong:
            report.wrong_tags[i] = wrong
        extras = extra_ingredients(recipe.ingredients, user_terms)
        if len(extras) > MAX_EXTRA_INGREDIENTS:
            report.add(i, "extra", f"uses too many ingredients the user does not have: {'; '.join(extras)}")
    return report


@node("diet_checker")
async def diet_checker(state: RecipeState) -> dict:
    """Code rules first (free), then an LLM critic for hidden violations of required diets."""
    req, result = state["request"], state["result"]
    required = diets(req)
    terms = state.get("search_terms") or [i.name for i in req.ingredients]
    report = check_rules(result, required, terms)
    if not required:
        return {"diet_report": report}

    try:
        critique = await complete_json(
            build_messages(
                "check_diets",
                _recipes_context(result),
                diets=", ".join(required),
                definitions="\n".join(f"  {d}: {DIET_DEFINITIONS[d]}" for d in required),
            ),
            DietCritique,
            temperature=0,
        )
    except Exception as err:  # the code rules still count
        log.warning("diet critic failed: %s", err)
        return {"diet_report": report, "errors": [f"diet_checker critic: {str(err)[:200]}"]}

    for entry in critique.recipes:
        if 1 <= entry.index <= len(result.recipes):
            for p in entry.problems:
                if p.diet in required:
                    report.add(entry.index, p.diet, f"breaks {p.diet}: {p.issue}")
    return {"diet_report": report}


@node("nutrition_agent")
async def nutrition_agent(state: RecipeState) -> dict:
    """LLM measures (food + grams), code looks up USDA values and calculates."""
    result = state["result"]
    weights = await complete_json(build_messages("measure_ingredients", _recipes_context(result)), IngredientWeights, temperature=0)
    nutrition: dict[int, NutritionResult] = {}
    for entry in weights.recipes:
        if 1 <= entry.index <= len(result.recipes):
            items = [(i.food, i.grams) for i in entry.items]
            portions = result.recipes[entry.index - 1].portions
            nutrition[entry.index] = await asyncio.to_thread(calculate, items, portions)
    return {"nutrition": nutrition}


# --------------------------------------------------------------------------
# Nodes: review and final
# --------------------------------------------------------------------------


@node("review")
async def review(state: RecipeState) -> dict:
    """Send recipes with problems back to the chef (max MAX_REVISIONS rounds)."""
    report = state.get("diet_report") or DietReport()
    rounds = state.get("revisions", 0)
    if not report.problems or rounds >= MAX_REVISIONS:
        return {"feedback": []}
    names = {i: r.name for i, r in enumerate(state["result"].recipes, start=1)}
    feedback = [f'Recipe {i} "{names.get(i, "?")}": {text}' for i, problems in report.problems.items() for _, text in problems]
    log.info("Revision %d: %s", rounds + 1, feedback)
    return {"feedback": feedback, "revisions": rounds + 1}


@node("final")
async def final(state: RecipeState) -> dict:
    """Apply USDA nutrition and remove diet tags that the checks disproved."""
    result = state.get("result")
    if not result:
        raise WorkflowError("no recipes were produced")
    report = state.get("diet_report") or DietReport()
    nutrition = state.get("nutrition") or {}

    recipes = []
    for i, recipe in enumerate(result.recipes, start=1):
        update: dict = {"nutritionSource": "estimate"}
        calc = nutrition.get(i)
        if calc and calc.reliable:
            update.update(nutrition=calc.nutrition, nutritionSource="USDA")
        # Tags still broken after the revisions must not be shown to the user.
        broken = report.wrong_tags.get(i, set()) | {kind for kind, _ in report.problems.get(i, []) if kind in DIET_VALUES}
        if broken:
            update["dietTags"] = [t for t in recipe.dietTags if t not in broken]
        recipes.append(recipe.model_copy(update=update))
    return {"final_result": RecipesResponse(recipes=recipes)}


# --------------------------------------------------------------------------
# Routing
# --------------------------------------------------------------------------

QUALITY = ["diet_checker", "nutrition_agent"]


def route_after_retriever(state: RecipeState) -> str:
    return "chef_agent" if state.get("candidates") else "fallback_chef"


def route_after_chef(state: RecipeState):
    if state.get("result") and state.get("chef") == "chef_agent":
        return QUALITY
    return "fallback_chef"


def route_after_fallback(state: RecipeState):
    return QUALITY if state.get("result") else "final"


def route_after_review(state: RecipeState) -> str:
    return state.get("chef", "chef_agent") if state.get("feedback") else "final"


def build_graph():
    graph = StateGraph(RecipeState)
    for name, fn in [
        ("input_agent", input_agent),
        ("retriever", retriever),
        ("chef_agent", chef_agent),
        ("fallback_chef", fallback_chef),
        ("diet_checker", diet_checker),
        ("nutrition_agent", nutrition_agent),
        ("review", review),
        ("final", final),
    ]:
        graph.add_node(name, fn)

    graph.add_edge(START, "input_agent")
    graph.add_edge("input_agent", "retriever")
    graph.add_conditional_edges("retriever", route_after_retriever, ["chef_agent", "fallback_chef"])
    graph.add_conditional_edges("chef_agent", route_after_chef, [*QUALITY, "fallback_chef"])
    graph.add_conditional_edges("fallback_chef", route_after_fallback, [*QUALITY, "final"])
    graph.add_edge(QUALITY, "review")  # waits for both parallel nodes
    graph.add_conditional_edges("review", route_after_review, ["chef_agent", "fallback_chef", "final"])
    graph.add_edge("final", END)
    return graph.compile()


workflow = build_graph()


async def stream_recipes(req: GenerateRequest):
    """Run the workflow and yield progress events as (event, data) tuples:

    ("step", {"step": "retriever", "status": "done" | "failed"})  after every node
    ("revision", {"round": 1, "problems": 2})                      when recipes go back to the chef
    ("result", {"recipes": [...]})                                 at the end

    Raises WorkflowError if no recipes could be produced.
    """
    errors: list[str] = []
    final_result = None
    async for chunk in workflow.astream({"request": req, "errors": [], "steps": []}, stream_mode="updates"):
        for name, update in chunk.items():
            update = update or {}
            errors += update.get("errors") or []
            failed = str(update.get("workflow_step", "")).endswith("_failed")
            yield "step", {"step": name, "status": "failed" if failed else "done"}
            if name == "review" and update.get("feedback"):
                yield "revision", {"round": update.get("revisions", 1), "problems": len(update["feedback"])}
            if update.get("final_result"):
                final_result = update["final_result"]
    if errors:
        log.info("Workflow finished with recovered errors: %s", errors)
    if final_result is None:
        raise WorkflowError("; ".join(errors or ["unknown error"]))
    yield "result", final_result.model_dump(exclude_none=True)


async def generate_recipes(req: GenerateRequest) -> RecipesResponse:
    """Run the workflow. Raises WorkflowError if no recipes could be produced."""
    state = await workflow.ainvoke({"request": req, "errors": [], "steps": []})
    if state.get("errors"):
        log.info("Workflow finished with recovered errors: %s", state["errors"])
    if not state.get("final_result"):
        raise WorkflowError("; ".join(state.get("errors") or ["unknown error"]))
    return state["final_result"]
