"""Wikibooks Cookbook raw data: download, filter, turn into plain text for the LLM.

Dataset: https://huggingface.co/datasets/gossminn/wikibooks-cookbook
License: CC BY-SA 4.0 (Wikibooks contributors). No LLM calls in this file.
"""

import hashlib
import json
import math
import random
import re
from pathlib import Path

import httpx

RAW_URL = "https://huggingface.co/datasets/gossminn/wikibooks-cookbook/resolve/main/recipes_parsed.json"
SOURCE_NAME = "Wikibooks Cookbook"
SOURCE_LICENSE = "CC BY-SA 4.0"

# Not useful for "what can I cook from my fridge".
SKIP_CATEGORIES = {"Beverage", "Spice mix", "Cocktail", "Liqueur", "Tea", "Coffee"}

# Sections that never help the LLM (only cost tokens).
DROP_SECTIONS = {"references", "see also", "external links", "gallery", "history", "nutrition"}

MAX_SOURCE_CHARS = 6000  # skip very long pages (cost, rarely a single recipe)
MIN_INGREDIENTS = 2
MIN_STEPS = 1


def download_raw(path: Path) -> None:
    """Download the raw JSON once (about 17 MB)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with httpx.stream("GET", RAW_URL, follow_redirects=True, timeout=120) as res:
        res.raise_for_status()
        with path.open("wb") as f:
            for chunk in res.iter_bytes():
                f.write(chunk)


def load_raw(path: Path) -> list[dict]:
    """Load the raw file and return the inner `recipe_data` dicts."""
    if not path.exists():
        raise FileNotFoundError(f"Raw data not found at {path}. Run the ingest with --download first.")
    items = json.loads(path.read_text(encoding="utf-8"))
    return [item["recipe_data"] for item in items if item.get("recipe_data", {}).get("url")]


def make_item_id(url: str) -> str:
    """Stable id from the source URL: same recipe -> same id on every run."""
    return "wb-" + hashlib.sha1(url.encode("utf-8")).hexdigest()[:12]


def category_name(raw: dict) -> str | None:
    """'/wiki/Category:Spice_mix_recipes' -> 'Spice mix'."""
    cat = (raw.get("infobox") or {}).get("category") or ""
    name = cat.rsplit("Category:", 1)[-1].removesuffix("_recipes").replace("_", " ").strip()
    return name or None


def _section(line: dict) -> str:
    return (line.get("section") or "").strip().lower().rstrip(":")


def _lines_in(raw: dict, keyword: str) -> list[str]:
    return [l["text"] for l in raw.get("text_lines", []) if keyword in _section(l) and l.get("text", "").strip()]


def to_source_text(raw: dict) -> str:
    """Compact plain-text version of a recipe page (title, infobox, sections)."""
    info = raw.get("infobox") or {}
    out = [f"Title: {raw.get('title', '').strip()}"]
    for key in ("category", "servings", "time", "difficulty"):
        value = category_name(raw) if key == "category" else info.get(key)
        if value:
            out.append(f"{key.capitalize()}: {value}")

    current = None
    for line in raw.get("text_lines", []):
        text = (line.get("text") or "").strip()
        section = _section(line)
        if not text or section in DROP_SECTIONS:
            continue
        if section != current:
            current = section
            out.append(f"\n## {line.get('section') or 'Intro'}")
        prefix = "- " if line.get("line_type") in ("ul", "ol") else ""
        out.append(prefix + text)
    return "\n".join(out)


def skip_reason(raw: dict) -> str | None:
    """Why a page is not usable as a recipe, or None if it is fine."""
    if category_name(raw) in SKIP_CATEGORIES:
        return f"category {category_name(raw)}"
    if len(_lines_in(raw, "ingredient")) < MIN_INGREDIENTS:
        return "too few ingredients"
    steps = [l for l in raw.get("text_lines", []) if any(k in _section(l) for k in ("procedure", "direction", "method", "instruction", "preparation"))]
    if len(steps) < MIN_STEPS:
        return "no procedure"
    if len(to_source_text(raw)) > MAX_SOURCE_CHARS:
        return "page too long"
    return None


_VARIANT_SUFFIX = re.compile(r"\b(i|ii|iii|iv|v|vi|vii|viii|ix|x|\d+)$")


def dish_key(title: str) -> str:
    """Same dish -> same key: 'Meatloaf III' / 'Meatloaf (Easy)' -> 'meatloaf'."""
    t = re.sub(r"\(.*?\)", " ", title.lower())
    t = re.sub(r"[^a-z ]", " ", t)
    t = " ".join(t.split())
    return _VARIANT_SUFFIX.sub("", t).strip()


def select_recipes(
    raw_items: list[dict],
    limit: int | None,
    seed: int = 42,
    preferred_ids: set[str] | frozenset[str] = frozenset(),
) -> list[dict]:
    """Pick a varied set of usable recipes.

    1. Variants of the same dish ('Meatloaf', 'Meatloaf II') count once.
    2. Categories share the slots in proportion to the square root of their
       size: big categories (desserts, soups) still get the most recipes, but
       far fewer than their raw share, so many more categories make it in.
    3. `preferred_ids` (recipes already processed) come first in their
       category, so they are kept and never paid for twice.

    Deterministic for a given seed: a smaller limit is a prefix of a larger one.
    """
    rng = random.Random(seed)
    usable = sorted((r for r in raw_items if skip_reason(r) is None), key=lambda r: r["url"])
    rng.shuffle(usable)
    usable.sort(key=lambda r: make_item_id(r["url"]) not in preferred_ids)  # stable: preferred first

    seen_dishes: set[str] = set()
    groups: dict[str, list[dict]] = {}
    for r in usable:
        dish = dish_key(r.get("title", ""))
        if dish in seen_dishes:
            continue
        seen_dishes.add(dish)
        groups.setdefault(category_name(r) or "Uncategorized", []).append(r)

    # Item i of a category with n items gets rank (i + 1) / sqrt(n). Taking the
    # lowest ranks gives each category about sqrt(n) * t slots.
    ranked = []
    for items in groups.values():
        root = math.sqrt(len(items))
        ranked += [((i + 1) / root, rng.random(), r) for i, r in enumerate(items)]
    ranked.sort(key=lambda x: (x[0], x[1]))
    ordered = [r for _, _, r in ranked]
    return ordered if limit is None else ordered[:limit]
