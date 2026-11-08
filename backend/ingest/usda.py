"""USDA FoodData Central (SR Legacy) -> data/usda_foods.jsonl.

Nutrients per 100 g for ~6,500 generic foods. Public domain (CC0).
https://fdc.nal.usda.gov/download-datasets

Run from the backend/ folder (downloads ~13 MB once):
    uv run python -m ingest.usda
"""

import io
import json
import logging
import zipfile
from pathlib import Path

import httpx

from core.config import BACKEND_DIR
from core.schemas import UsdaFood

log = logging.getLogger("usda")

SR_LEGACY_URL = "https://fdc.nal.usda.gov/fdc-datasets/FoodData_Central_sr_legacy_food_json_2021-10-28.zip"
RAW_PATH = BACKEND_DIR / "data" / "raw" / "usda_sr_legacy.zip"
OUT_PATH = BACKEND_DIR / "data" / "usda_foods.jsonl"

# Nutrient ids in FoodData Central.
NUTRIENTS = {1008: "calories", 1003: "protein", 1005: "carbs", 1004: "fat"}

# Prepared dishes and brands: never what a recipe ingredient means.
SKIP_CATEGORIES = {
    "Baby Foods",
    "Fast Foods",
    "Restaurant Foods",
    "Meals, Entrees, and Side Dishes",
    "American Indian/Alaska Native Foods",
}
MAX_PORTIONS = 6


def download(path: Path = RAW_PATH) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with httpx.stream("GET", SR_LEGACY_URL, follow_redirects=True, timeout=180) as res:
        res.raise_for_status()
        with path.open("wb") as f:
            for chunk in res.iter_bytes():
                f.write(chunk)


def load_raw_foods(path: Path = RAW_PATH) -> list[dict]:
    with zipfile.ZipFile(path) as z:
        name = next(n for n in z.namelist() if n.endswith(".json"))
        with z.open(name) as f:
            data = json.load(io.TextIOWrapper(f, encoding="utf-8"))
    return data["SRLegacyFoods"]


def to_food(raw: dict) -> UsdaFood | None:
    """Raw FDC food -> compact record, or None if unusable."""
    category = (raw.get("foodCategory") or {}).get("description", "")
    if category in SKIP_CATEGORIES:
        return None
    values = {}
    for n in raw.get("foodNutrients", []):
        key = NUTRIENTS.get((n.get("nutrient") or {}).get("id"))
        if key and n.get("amount") is not None:
            values[key] = round(float(n["amount"]), 2)
    if "calories" not in values:
        return None
    portions = [
        {"label": " ".join(str(x) for x in (p.get("amount"), p.get("modifier")) if x), "grams": p["gramWeight"]}
        for p in raw.get("foodPortions", [])
        if p.get("gramWeight")
    ][:MAX_PORTIONS]
    return UsdaFood(
        fdcId=raw["fdcId"],
        description=raw["description"],
        category=category,
        per100g={k: values.get(k, 0.0) for k in NUTRIENTS.values()},
        portions=portions,
    )


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    if not RAW_PATH.exists():
        log.info("Downloading USDA SR Legacy (~13 MB) ...")
        download()
    foods = [f for f in (to_food(r) for r in load_raw_foods()) if f]
    with OUT_PATH.open("w", encoding="utf-8") as out:
        for food in foods:
            out.write(food.model_dump_json() + "\n")
    log.info("Wrote %d foods to %s", len(foods), OUT_PATH)


if __name__ == "__main__":
    main()
