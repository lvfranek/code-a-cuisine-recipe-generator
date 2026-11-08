"""Ingest CLI: Wikibooks raw data -> LLM -> data/recipes.jsonl.

Run from the backend/ folder:
    uv run python -m ingest.run --download --limit 50

- Resumable: recipes already in recipes.jsonl are skipped (no double cost).
- Raising --limit later only processes the new recipes.
- Failures are logged to data/ingest_errors.jsonl; the batch keeps going.
- --rebuild starts from scratch (asks first, makes a backup).
"""

import argparse
import asyncio
import json
import logging
import shutil
import time
from pathlib import Path

from core.llm import OutOfCreditsError, usage
from core.recipes import load_records
from ingest.structure import structure_recipe
from ingest.wikibooks import category_name, download_raw, load_raw, make_item_id, select_recipes

log = logging.getLogger("ingest")

DATA_DIR = Path(__file__).resolve().parents[1] / "data"
RAW_PATH = DATA_DIR / "raw" / "wikibooks_recipes_parsed.json"
OUT_PATH = DATA_DIR / "recipes.jsonl"
ERR_PATH = DATA_DIR / "ingest_errors.jsonl"


def append_jsonl(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(data, ensure_ascii=False) + "\n")


def backup(path: Path) -> Path | None:
    if not path.exists():
        return None
    target = path.with_name(f"{path.stem}.backup-{time.strftime('%Y%m%d-%H%M%S')}{path.suffix}")
    shutil.copy2(path, target)
    return target


async def process(raw_items: list[dict], out_path: Path, err_path: Path, concurrency: int) -> tuple[int, int]:
    """Structure all items in parallel (bounded). Returns (ok, failed)."""
    sem = asyncio.Semaphore(concurrency)
    ok = failed = 0
    out_of_credits = asyncio.Event()

    async def one(raw: dict) -> None:
        nonlocal ok, failed
        async with sem:
            if out_of_credits.is_set():
                return  # stop cleanly; the next run picks these up again
            try:
                record = await structure_recipe(raw)
            except OutOfCreditsError as err:
                if not out_of_credits.is_set():
                    log.error("%s Stopping, already saved recipes are kept.", err)
                out_of_credits.set()
                return
            except Exception as err:  # one bad recipe must not stop the batch
                failed += 1
                log.warning("FAILED %s: %s", raw.get("title"), str(err)[:200])
                append_jsonl(err_path, {"itemId": make_item_id(raw["url"]), "url": raw["url"], "error": str(err)[:1000]})
                return
            append_jsonl(out_path, record.model_dump())
            ok += 1
            log.info("[%d] %s -> %s, %s", ok, record.name, record.cuisine, record.dietTags or "-")

    await asyncio.gather(*(one(r) for r in raw_items))
    return ok, failed


def main() -> None:
    parser = argparse.ArgumentParser(description="Import Wikibooks recipes into data/recipes.jsonl")
    parser.add_argument("--limit", type=int, default=50, help="total number of recipes wanted (default 50)")
    parser.add_argument("--concurrency", type=int, default=4, help="parallel LLM calls (default 4)")
    parser.add_argument("--download", action="store_true", help="download the raw dataset if missing")
    parser.add_argument("--rebuild", action="store_true", help="start from scratch (backup + confirmation)")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)

    if args.download and not RAW_PATH.exists():
        log.info("Downloading raw dataset to %s ...", RAW_PATH)
        download_raw(RAW_PATH)

    if args.rebuild and OUT_PATH.exists():
        answer = input(f"Delete all {len(load_records(OUT_PATH))} records in {OUT_PATH.name}? A backup is made first. [yes/no] ")
        if answer.strip().lower() != "yes":
            log.info("Aborted, nothing changed.")
            return
        log.info("Backup: %s", backup(OUT_PATH))
        OUT_PATH.unlink()

    done = {r.itemId for r in load_records(OUT_PATH)}
    selected = select_recipes(load_raw(RAW_PATH), args.limit, preferred_ids=done)
    todo = [r for r in selected if make_item_id(r["url"]) not in done]
    categories = {category_name(r) for r in selected}
    log.info(
        "Selected %d recipes from %d categories: %d already done, %d to process.",
        len(selected), len(categories), len(selected) - len(todo), len(todo),
    )
    if not todo:
        return

    ok, failed = asyncio.run(process(todo, OUT_PATH, ERR_PATH, args.concurrency))
    total = len(load_records(OUT_PATH))
    log.info("Done: %d new, %d failed, %d total in %s.", ok, failed, total, OUT_PATH.name)
    log.info(
        "LLM usage: %d calls, %d prompt + %d completion tokens, cost $%.4f",
        usage.calls, usage.prompt_tokens, usage.completion_tokens, usage.cost,
    )


if __name__ == "__main__":
    main()
