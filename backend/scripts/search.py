"""Try the recipe search from the terminal.

Run from the backend/ folder:
    uv run python -m scripts.search "chicken, rice, onion"
    uv run python -m scripts.search "tomato, pasta, garlic" --diet Vegetarian --max-minutes 30
    uv run python -m scripts.search "beans, rice" --cuisine Mexican Indian -k 3
"""

import argparse

from core.retrieval import IndexNotReadyError, SearchFilters, SearchHit, search_recipes
from core.schemas import CUISINE_VALUES, DIET_VALUES


def print_hit(rank: int, hit: SearchHit) -> None:
    r = hit.record
    print(f"\n{rank}. {r.name}  [{r.cuisine}, {r.category}, {r.cookTimeMinutes} min]")
    print(f"   score {hit.score:.2f} = similarity {hit.similarity:.2f} + coverage {hit.coverage:.0%}")
    print(f"   diet: {', '.join(r.dietTags) or '-'}")
    print(f"   you have: {', '.join(hit.matched) or '-'}")
    print(f"   missing:  {', '.join(hit.missing) or '-'}")
    print(f"   source:   {r.source.url}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Search recipes by ingredients")
    parser.add_argument("ingredients", help='comma-separated, e.g. "chicken, rice, onion"')
    parser.add_argument("--diet", nargs="*", default=[], choices=DIET_VALUES)
    parser.add_argument("--cuisine", nargs="*", default=[], choices=CUISINE_VALUES)
    parser.add_argument("--max-minutes", type=int, default=None)
    parser.add_argument("-k", type=int, default=5, help="number of results")
    args = parser.parse_args()

    filters = SearchFilters(diets=args.diet, cuisines=args.cuisine, max_minutes=args.max_minutes)
    try:
        hits = search_recipes(args.ingredients.split(","), filters, k=args.k)
    except IndexNotReadyError as err:
        raise SystemExit(f"Index not ready: {err}") from err

    if not hits:
        print("No recipes found for these filters. Try fewer filters or a longer cooking time.")
        return
    for i, hit in enumerate(hits, start=1):
        print_hit(i, hit)


if __name__ == "__main__":
    main()
