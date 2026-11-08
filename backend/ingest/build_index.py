"""Build the ChromaDB vector index from data/recipes.jsonl.

Run from the backend/ folder:
    uv run python -m ingest.build_index            # add / update (safe to re-run)
    uv run python -m ingest.build_index --rebuild  # backup, then build from scratch
"""

import argparse
import logging
import shutil
import time

from core.config import BACKEND_DIR, get_settings
from core.nutrition import COLLECTION as FOOD_COLLECTION
from core.nutrition import upsert_foods
from core.recipes import load_records
from core.retrieval import COLLECTION, EMBEDDING_MODEL, get_client, get_collection, upsert_records
from core.schemas import UsdaFood

log = logging.getLogger("build_index")

USDA_PATH = BACKEND_DIR / "data" / "usda_foods.jsonl"


def backup_index() -> str | None:
    path = get_settings().chroma_path
    if not path.exists():
        return None
    target = path.with_name(f"{path.name}.backup-{time.strftime('%Y%m%d-%H%M%S')}")
    shutil.copytree(path, target)
    return str(target)


def main() -> None:
    parser = argparse.ArgumentParser(description="Build the recipe vector index")
    parser.add_argument("--rebuild", action="store_true", help="delete and rebuild (backup first)")
    parser.add_argument("--yes", action="store_true", help="skip the confirmation for --rebuild (for scripts)")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    s = get_settings()
    records = load_records(s.recipes_path)
    if not records:
        raise SystemExit(f"No recipes in {s.recipes_path}. Run the ingest first: uv run python -m ingest.run")

    if args.rebuild and s.chroma_path.exists():
        if not args.yes and input(f"Delete and rebuild the index in {s.chroma_path}? A backup is made first. [yes/no] ").strip().lower() != "yes":
            log.info("Aborted, nothing changed.")
            return
        log.info("Backup: %s", backup_index())
        for name in (COLLECTION, FOOD_COLLECTION):
            try:
                get_client().delete_collection(name)
            except Exception:
                pass  # collection did not exist

    start = time.time()
    log.info("Embedding %d recipes with %s ...", len(records), EMBEDDING_MODEL)
    count = upsert_records(get_collection(create=True), records)
    log.info("Done in %.1fs: collection '%s' holds %d recipes (%s).", time.time() - start, COLLECTION, count, s.chroma_path)

    foods = load_foods()
    if not foods:
        log.warning("No USDA foods in %s, skipping nutrition index. Run: uv run python -m ingest.usda", USDA_PATH)
        return
    start = time.time()
    log.info("Embedding %d USDA foods ...", len(foods))
    client = get_client()
    collection = client.get_or_create_collection(
        FOOD_COLLECTION, configuration={"hnsw": {"space": "cosine"}}, embedding_function=None
    )
    count = upsert_foods(collection, foods)
    log.info("Done in %.1fs: collection '%s' holds %d foods.", time.time() - start, FOOD_COLLECTION, count)


def load_foods() -> list[UsdaFood]:
    if not USDA_PATH.exists():
        return []
    return [UsdaFood.model_validate_json(line) for line in USDA_PATH.read_text(encoding="utf-8").splitlines() if line.strip()]


if __name__ == "__main__":
    main()
