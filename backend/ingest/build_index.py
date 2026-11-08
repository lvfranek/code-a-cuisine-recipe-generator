"""Build the ChromaDB vector index from data/recipes.jsonl.

Run from the backend/ folder:
    uv run python -m ingest.build_index            # add / update (safe to re-run)
    uv run python -m ingest.build_index --rebuild  # backup, then build from scratch
"""

import argparse
import logging
import shutil
import time

from core.config import get_settings
from core.recipes import load_records
from core.retrieval import COLLECTION, EMBEDDING_MODEL, get_client, get_collection, upsert_records

log = logging.getLogger("build_index")


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
        try:
            get_client().delete_collection(COLLECTION)
        except Exception:
            pass  # collection did not exist

    start = time.time()
    log.info("Embedding %d recipes with %s ...", len(records), EMBEDDING_MODEL)
    count = upsert_records(get_collection(create=True), records)
    log.info("Done in %.1fs: collection '%s' holds %d recipes (%s).", time.time() - start, COLLECTION, count, s.chroma_path)


if __name__ == "__main__":
    main()
