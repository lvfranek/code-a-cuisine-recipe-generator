"""Evaluation: how often do generated recipes break the requested diet,
with and without the diet checker agent?

For every case in eval/cases.json the full workflow runs twice:
  A) without diet checker (chef -> nutrition -> final)
  B) with diet checker   (chef -> diet check + nutrition -> revisions -> final)
Every recipe is then graded by an independent judge (different model family)
and by the deterministic diet rules.

Run from the backend/ folder (costs a few cents):
    uv run python -m eval.run
Writes eval/results/latest.json and eval/RESULTS.md.
"""

import argparse
import asyncio
import json
import logging
import statistics
import time
from datetime import date
from pathlib import Path

from core import diet_rules
from core.agents import graph as graph_module
from core.llm import usage
from core.schemas import GenerateRequest, Recipe
from eval.judge import JUDGE_MODEL, judge

EVAL_DIR = Path(__file__).resolve().parent
CASES_PATH = EVAL_DIR / "cases.json"
RESULTS_DIR = EVAL_DIR / "results"
MODES = {"without_checker": False, "with_checker": True}

log = logging.getLogger("eval")


def load_cases(path: Path = CASES_PATH) -> list[dict]:
    return json.loads(path.read_text(encoding="utf-8"))


def to_request(case: dict) -> GenerateRequest:
    return GenerateRequest.model_validate({
        "ingredients": [{"name": n} for n in case["ingredients"]],
        "portions": 2,
        "cookingTime": "medium",
        "cuisines": ["Any"],
        "dietPreferences": case["diets"],
    })


async def run_case(workflow, case: dict, sem: asyncio.Semaphore) -> dict:
    async with sem:
        start = time.perf_counter()
        try:
            state = await workflow.ainvoke({"request": to_request(case), "errors": [], "steps": []})
        except Exception as err:  # never let one case stop the evaluation
            return {"id": case["id"], "error": str(err)[:300]}
        result = state.get("final_result")
        if result is None:
            return {"id": case["id"], "error": "; ".join(state.get("errors") or ["no result"])[:300]}
        return {
            "id": case["id"],
            "seconds": round(time.perf_counter() - start, 2),
            "revisions": state.get("revisions", 0),
            "recipes": [r.model_dump(include={"name", "dietTags", "ingredients", "instructions"}) for r in result.recipes],
        }


def rule_violations(recipe: Recipe | dict, diets: list[str]) -> list[str]:
    r = recipe if isinstance(recipe, dict) else recipe.model_dump()
    out = []
    for d in diets:
        lines = [r["name"], *r["ingredients"]] if d in ("Vegan", "Vegetarian") else list(r["ingredients"])
        out += [f"{d}: {v}" for v in diet_rules.violations(lines, d)]
    return out


async def grade_case(case: dict, run: dict, sem: asyncio.Semaphore) -> None:
    """Adds per-recipe judge and rule verdicts to `run` (in place)."""
    if "recipes" not in run:
        return
    recipes = [Recipe(id=i, **r) for i, r in enumerate(run["recipes"], start=1)]
    async with sem:
        try:
            verdicts = await judge(recipes, case["diets"])
        except Exception as err:
            run["judge_error"] = str(err)[:300]
            verdicts = {}
    for i, r in enumerate(run["recipes"], start=1):
        judged = verdicts.get(i)
        r["judge"] = None if judged is None else [f"{v.diet}: {v.ingredient}" for v in judged]
        r["rules"] = rule_violations(r, case["diets"])
        r["claims_diet"] = all(d in r["dietTags"] for d in case["diets"])


def summarize(cases: list[dict], runs: dict[str, list[dict]], costs: dict[str, float]) -> dict:
    by_id = {c["id"]: c for c in cases}
    summary = {}
    for mode, results in runs.items():
        recipes = [r for run in results for r in run.get("recipes", [])]
        judged = [r for r in recipes if r.get("judge") is not None]
        bad_judge = [r for r in judged if r["judge"]]
        bad_rules = [r for r in recipes if r["rules"]]
        wrong_label = [r for r in judged if r["judge"] and r["claims_diet"]]
        ok_runs = [run for run in results if "recipes" in run]
        per_diet = {}
        for run in ok_runs:
            for d in by_id[run["id"]]["diets"]:
                stats = per_diet.setdefault(d, {"recipes": 0, "violating": 0})
                for r in run["recipes"]:
                    if r.get("judge") is not None:
                        stats["recipes"] += 1
                        stats["violating"] += any(v.startswith(f"{d}:") for v in r["judge"])
        summary[mode] = {
            "cases": len(results),
            "failed_cases": len(results) - len(ok_runs),
            "recipes": len(recipes),
            "judged_recipes": len(judged),
            "violating_recipes_judge": len(bad_judge),
            "violation_rate_judge": round(len(bad_judge) / len(judged), 3) if judged else None,
            "violating_recipes_rules": len(bad_rules),
            "violation_rate_rules": round(len(bad_rules) / len(recipes), 3) if recipes else None,
            "wrong_diet_label": len(wrong_label),
            "wrong_label_rate": round(len(wrong_label) / len(judged), 3) if judged else None,
            "avg_seconds": round(statistics.mean(r["seconds"] for r in ok_runs), 1) if ok_runs else None,
            "avg_revisions": round(statistics.mean(r["revisions"] for r in ok_runs), 2) if ok_runs else None,
            "cost_usd": round(costs.get(mode, 0.0), 4),
            "cost_per_request_usd": round(costs.get(mode, 0.0) / len(ok_runs), 5) if ok_runs else None,
            "per_diet": per_diet,
        }
    return summary


def pct(x: float | None) -> str:
    return "–" if x is None else f"{x * 100:.0f} %"


def markdown_report(summary: dict, cases: list[dict], runs: dict[str, list[dict]], judge_cost: float) -> str:
    a, b = summary["without_checker"], summary["with_checker"]
    lines = [
        "# Evaluation: diet checker",
        "",
        f"Run on {date.today().isoformat()} with `uv run python -m eval.run`. "
        f"{len(cases)} requests ([cases.json](cases.json)), most with a deliberate trap ingredient "
        "that breaks the requested diet (e.g. honey for Vegan, soy sauce for Gluten-Free).",
        "Each request runs through the full workflow twice: without and with the diet checker agent. "
        f"Every recipe is then graded by an independent judge (`{JUDGE_MODEL}`, a different model family "
        "than the app's model) and by the deterministic diet rules.",
        "",
        "| | without diet checker | with diet checker |",
        "|---|---:|---:|",
        f"| Recipes graded | {a['judged_recipes']} | {b['judged_recipes']} |",
        f"| **Recipes breaking the requested diet** (judge) | **{a['violating_recipes_judge']} ({pct(a['violation_rate_judge'])})** | **{b['violating_recipes_judge']} ({pct(b['violation_rate_judge'])})** |",
        f"| Recipes breaking the diet (rules) | {a['violating_recipes_rules']} ({pct(a['violation_rate_rules'])}) | {b['violating_recipes_rules']} ({pct(b['violation_rate_rules'])}) |",
        f"| Recipes **labelled** with the diet but breaking it | {a['wrong_diet_label']} ({pct(a['wrong_label_rate'])}) | {b['wrong_diet_label']} ({pct(b['wrong_label_rate'])}) |",
        f"| Avg. time per request | {a['avg_seconds']} s | {b['avg_seconds']} s |",
        f"| Avg. revision rounds | {a['avg_revisions']} | {b['avg_revisions']} |",
        f"| LLM cost per request | ${a['cost_per_request_usd']} | ${b['cost_per_request_usd']} |",
        f"| Failed requests | {a['failed_cases']} | {b['failed_cases']} |",
        "",
        "## Per diet (judge)",
        "",
        "| Diet | without checker | with checker |",
        "|---|---:|---:|",
    ]
    for d in sorted(set(a["per_diet"]) | set(b["per_diet"])):
        pa, pb = a["per_diet"].get(d, {}), b["per_diet"].get(d, {})
        fa = f"{pa.get('violating', 0)}/{pa.get('recipes', 0)}"
        fb = f"{pb.get('violating', 0)}/{pb.get('recipes', 0)}"
        lines.append(f"| {d} | {fa} | {fb} |")
    lines += [
        "",
        "## Remaining violations with the checker",
        "",
    ]
    remaining = [
        (run["id"], r["name"], r["judge"])
        for run in runs["with_checker"]
        for r in run.get("recipes", [])
        if r.get("judge")
    ]
    lines += [f"- `{cid}` {name}: {', '.join(v)}" for cid, name, v in remaining] or ["None."]
    lines += [
        "",
        "## Notes",
        "",
        "- Method, history of improvements and limitations: [README.md](README.md).",
        "- *Rules* use the same keyword rules as the checker, so they are not an independent measure; the judge is.",
        "- LLM output varies between runs; numbers from a single run of each request.",
        f"- Judge cost for this run: ${judge_cost:.4f}.",
    ]
    return "\n".join(lines) + "\n"


async def main_async(limit: int | None, concurrency: int) -> None:
    cases = load_cases()[:limit] if limit else load_cases()
    sem = asyncio.Semaphore(concurrency)
    runs: dict[str, list[dict]] = {}
    costs: dict[str, float] = {}

    for mode, with_checker in MODES.items():
        workflow = graph_module.build_graph(with_diet_checker=with_checker)
        before = usage.cost
        log.info("Running %d cases %s ...", len(cases), mode)
        runs[mode] = await asyncio.gather(*(run_case(workflow, c, sem) for c in cases))
        costs[mode] = usage.cost - before

    before = usage.cost
    log.info("Grading with %s ...", JUDGE_MODEL)
    await asyncio.gather(*(grade_case(c, run, sem) for mode in MODES for c, run in zip(cases, runs[mode])))
    judge_cost = usage.cost - before

    summary = summarize(cases, runs, costs)
    RESULTS_DIR.mkdir(exist_ok=True)
    (RESULTS_DIR / "latest.json").write_text(json.dumps({"summary": summary, "runs": runs}, indent=2, ensure_ascii=False))
    (EVAL_DIR / "RESULTS.md").write_text(markdown_report(summary, cases, runs, judge_cost), encoding="utf-8")
    log.info("Summary: %s", json.dumps({m: {k: v for k, v in s.items() if k != "per_diet"} for m, s in summary.items()}, indent=1))
    log.info("Total cost incl. judge: $%.4f", usage.cost)


def main() -> None:
    parser = argparse.ArgumentParser(description="Diet checker evaluation")
    parser.add_argument("--limit", type=int, default=None, help="only the first N cases (quick check)")
    parser.add_argument("--concurrency", type=int, default=3)
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    for noisy in ("httpx", "core.agents.graph", "core.generate", "core.retrieval"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
    asyncio.run(main_async(args.limit, args.concurrency))


if __name__ == "__main__":
    main()
