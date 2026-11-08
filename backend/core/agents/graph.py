"""Recipe workflow as a LangGraph graph.

    START -> input_agent -> retriever --(candidates)--> chef_agent --(ok)--> final -> END
                                     \\                            \\(failed)
                                      \\--(none)----------------> fallback_chef -> final

- Shared state (`RecipeState`): every node reads it and returns only its own fields.
- Every node is wrapped by `@node`: errors are stored in `errors` instead of
  crashing the workflow, and `workflow_step` is set for progress tracking.
- Only the retriever touches the vector database.
"""

import asyncio
import logging
import operator
import time
from functools import wraps
from typing import Annotated, TypedDict

from langgraph.graph import END, START, StateGraph

from core.agents.config import build_messages
from core.generate import (
    RECIPE_COUNT,
    adapted_schema,
    candidates_context,
    example_json,
    request_context,
    retrieve_candidates,
    to_rag_response,
    to_response,
)
from core.llm import complete_json
from core.retrieval import SearchHit
from core.schemas import GenerateRequest, IngredientTerms, RecipeDrafts, RecipesResponse

log = logging.getLogger(__name__)


class WorkflowError(RuntimeError):
    """The workflow finished without recipes."""


class RecipeState(TypedDict, total=False):
    request: GenerateRequest  # input (validated)
    search_terms: list[str]  # input_agent
    candidates: list[SearchHit]  # retriever
    result: RecipesResponse  # chef_agent / fallback_chef
    workflow_step: str  # last finished step
    errors: Annotated[list[str], operator.add]  # every node may append


def node(name: str):
    """Wrap a node: timing log, workflow_step, and errors stored instead of raised."""

    def decorator(fn):
        @wraps(fn)
        async def wrapper(state: RecipeState) -> dict:
            start = time.perf_counter()
            try:
                update = await fn(state)
            except Exception as err:
                log.warning("%s failed after %.1fs: %s", name, time.perf_counter() - start, str(err)[:300])
                return {"errors": [f"{name}: {str(err)[:300]}"], "workflow_step": f"{name}_failed"}
            log.info("%s done in %.1fs", name, time.perf_counter() - start)
            return {**update, "workflow_step": name}

        return wrapper

    return decorator


# --------------------------------------------------------------------------
# Nodes
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
        f"{request_context(req)}\n\n{candidates_context(hits)}",
        count=count,
        example=example_json(req.portions, hits[0].record.itemId),
    )
    adapted = await complete_json(messages, adapted_schema([h.record.itemId for h in hits]))
    return {"result": to_rag_response(adapted, hits, req.portions)}


@node("fallback_chef")
async def fallback_chef(state: RecipeState) -> dict:
    """Free generation when there are no candidates or the chef failed."""
    req = state["request"]
    messages = build_messages(
        "create_recipes", request_context(req), count=RECIPE_COUNT, example=example_json(req.portions)
    )
    drafts = await complete_json(messages, RecipeDrafts)
    return {"result": to_response(drafts, req.portions)}


@node("final")
async def final(state: RecipeState) -> dict:
    if not state.get("result"):
        raise WorkflowError("no recipes were produced")
    return {}


# --------------------------------------------------------------------------
# Routing
# --------------------------------------------------------------------------


def route_after_retriever(state: RecipeState) -> str:
    return "chef_agent" if state.get("candidates") else "fallback_chef"


def route_after_chef(state: RecipeState) -> str:
    return "final" if state.get("result") else "fallback_chef"


def build_graph():
    graph = StateGraph(RecipeState)
    graph.add_node("input_agent", input_agent)
    graph.add_node("retriever", retriever)
    graph.add_node("chef_agent", chef_agent)
    graph.add_node("fallback_chef", fallback_chef)
    graph.add_node("final", final)

    graph.add_edge(START, "input_agent")
    graph.add_edge("input_agent", "retriever")
    graph.add_conditional_edges("retriever", route_after_retriever, ["chef_agent", "fallback_chef"])
    graph.add_conditional_edges("chef_agent", route_after_chef, ["final", "fallback_chef"])
    graph.add_edge("fallback_chef", "final")
    graph.add_edge("final", END)
    return graph.compile()


workflow = build_graph()


async def generate_recipes(req: GenerateRequest) -> RecipesResponse:
    """Run the workflow. Raises WorkflowError if no recipes could be produced."""
    state = await workflow.ainvoke({"request": req, "errors": []})
    if state.get("errors"):
        log.info("Workflow finished with recovered errors: %s", state["errors"])
    if not state.get("result"):
        raise WorkflowError("; ".join(state.get("errors") or ["unknown error"]))
    return state["result"]
