import asyncio
import json

import pytest
from pydantic import ValidationError

from core.schemas import RecipeExtraction
from ingest import run, structure
from ingest.structure import EXAMPLE_OUTPUT, structure_recipe
from ingest.wikibooks import (
    category_name,
    dish_key,
    make_item_id,
    select_recipes,
    skip_reason,
    to_source_text,
)


def raw_recipe(url="https://en.wikibooks.org/wiki/Cookbook:Soup", category="Soup_recipes", n_ing=3, extra=None):
    lines = [{"text": "A family favourite.", "line_type": "p", "section": None}]
    lines += [{"text": f"{i + 1} cup ingredient {i}", "line_type": "ul", "section": "Ingredients"} for i in range(n_ing)]
    lines += [{"text": "Cook everything.", "line_type": "ol", "section": "Procedure"}]
    lines += extra or []
    return {
        "url": url,
        "title": "Soup",
        "infobox": {"category": f"/wiki/Category:{category}", "servings": "4", "time": "30 minutes", "difficulty": None},
        "text_lines": lines,
    }


# ------------------------------ raw handling ------------------------------


def test_item_id_is_stable_and_unique():
    a = make_item_id("https://x/a")
    assert a == make_item_id("https://x/a")
    assert a != make_item_id("https://x/b")
    assert a.startswith("wb-")


def test_category_name():
    assert category_name(raw_recipe(category="Spice_mix_recipes")) == "Spice mix"
    assert category_name({"infobox": None}) is None


def test_source_text_keeps_sections_and_drops_references():
    extra = [{"text": "Some book, 1990", "line_type": "ul", "section": "References"}]
    text = to_source_text(raw_recipe(extra=extra))
    assert "Title: Soup" in text and "Servings: 4" in text and "Category: Soup" in text
    assert "## Ingredients" in text and "- 1 cup ingredient 0" in text
    assert "## Procedure" in text
    assert "Some book" not in text


def test_skip_reasons():
    assert skip_reason(raw_recipe()) is None
    assert skip_reason(raw_recipe(category="Beverage_recipes")) == "category Beverage"
    assert skip_reason(raw_recipe(n_ing=1)) == "too few ingredients"


def titled(url, title, category):
    r = raw_recipe(url=url, category=category)
    r["title"] = title
    return r


def test_selection_is_stable_prefix():
    items = [titled(f"https://x/{i}", f"Dish {chr(65 + i)}", "Soup_recipes") for i in range(20)]
    small = select_recipes(items, 5)
    big = select_recipes(list(reversed(items)), 15)
    assert big[:5] == small  # input order does not matter, small is a prefix of big


def test_dish_key_groups_variants():
    assert dish_key("Meatloaf III") == dish_key("Meatloaf") == dish_key("Meatloaf (Easy)") == "meatloaf"
    assert dish_key("Tres Leches Cake I") == "tres leches cake"
    assert dish_key("Pho") != dish_key("Pita")


def test_selection_drops_duplicate_dishes():
    items = [titled("https://x/1", "Meatloaf", "Meat_recipes"), titled("https://x/2", "Meatloaf II", "Meat_recipes")]
    assert len(select_recipes(items, None)) == 1


def test_selection_balances_categories():
    big = [titled(f"https://x/d{i}", f"Dessert {chr(65 + i % 26)}{chr(65 + i // 26)}", "Dessert_recipes") for i in range(100)]
    small = [titled(f"https://x/s{i}", f"Soup {chr(65 + i)}", "Soup_recipes") for i in range(4)]
    picked = select_recipes(big + small, 12)
    soups = sum(1 for r in picked if category_name(r) == "Soup")
    assert soups >= 2  # plain random would give ~0.5 soups out of 12


def test_preferred_recipes_are_kept():
    items = [titled(f"https://x/{i}", f"Dish {chr(65 + i)}", "Soup_recipes") for i in range(20)]
    preferred = {make_item_id("https://x/19")}
    picked = select_recipes(items, 3, preferred_ids=preferred)
    assert make_item_id("https://x/19") in {make_item_id(r["url"]) for r in picked}


# ------------------------------- LLM step -------------------------------


def fake_chat_returning(payload):
    async def _chat(messages, **kwargs):
        return json.dumps(payload)

    return _chat


def test_structure_recipe_sets_id_source_and_category_in_code(monkeypatch):
    monkeypatch.setattr("core.llm.chat", fake_chat_returning(EXAMPLE_OUTPUT))
    raw = raw_recipe()
    record = asyncio.run(structure_recipe(raw))
    assert record.itemId == make_item_id(raw["url"])
    assert record.category == "Soup"
    assert record.source.url == raw["url"]
    assert record.source.license == "CC BY-SA 4.0"
    assert record.ingredients[0].name == "tomato"


def test_unknown_cuisine_or_diet_is_rejected():
    with pytest.raises(ValidationError):
        RecipeExtraction.model_validate({**EXAMPLE_OUTPUT, "cuisine": "Martian"})
    with pytest.raises(ValidationError):
        RecipeExtraction.model_validate({**EXAMPLE_OUTPUT, "dietTags": ["Carnivore"]})


def test_example_output_is_valid():
    # The one-shot example in the prompt must itself pass validation.
    RecipeExtraction.model_validate(EXAMPLE_OUTPUT)


# ------------------------------ batch runner ------------------------------


def test_process_writes_records_and_logs_failures(tmp_path, monkeypatch):
    good, bad = raw_recipe(url="https://x/good"), raw_recipe(url="https://x/bad")

    async def fake_structure(raw):
        if raw is bad:
            raise ValueError("model broke")
        return await structure_recipe(raw)

    monkeypatch.setattr("core.llm.chat", fake_chat_returning(EXAMPLE_OUTPUT))
    monkeypatch.setattr(run, "structure_recipe", fake_structure)
    out, err = tmp_path / "recipes.jsonl", tmp_path / "errors.jsonl"

    ok, failed = asyncio.run(run.process([good, bad], out, err, concurrency=2))

    assert (ok, failed) == (1, 1)
    records = run.load_records(out)
    assert [r.itemId for r in records] == [make_item_id("https://x/good")]
    assert "model broke" in err.read_text()


def test_backup_copies_file(tmp_path):
    f = tmp_path / "recipes.jsonl"
    f.write_text("data")
    copy = run.backup(f)
    assert copy.read_text() == "data" and copy != f
    assert structure.SOURCE_NAME == "Wikibooks Cookbook"


def test_batch_stops_when_credits_run_out(tmp_path, monkeypatch):
    from core.llm import OutOfCreditsError

    calls = []

    async def no_credits(raw):
        calls.append(raw["url"])
        raise OutOfCreditsError("no credits")

    monkeypatch.setattr(run, "structure_recipe", no_credits)
    items = [raw_recipe(url=f"https://x/{i}") for i in range(10)]
    ok, failed = asyncio.run(run.process(items, tmp_path / "o.jsonl", tmp_path / "e.jsonl", concurrency=1))
    assert (ok, failed) == (0, 0)
    assert len(calls) == 1  # stopped after the first 402
    assert not (tmp_path / "e.jsonl").exists()  # not logged as recipe errors
