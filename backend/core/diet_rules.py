"""Deterministic diet rules: which ingredient lines clearly break a diet.

Fast, free and predictable. Catches the obvious cases (egg in "Vegan", soy
sauce in "Gluten-Free"). Hidden ingredients (e.g. Worcestershire sauce
contains anchovy) are left to the LLM critic in the diet checker.
"""

import re

MEAT_FISH = [
    "chicken", "beef", "pork", "bacon", "ham", "lamb", "mutton", "turkey", "duck", "goose", "veal",
    "venison", "sausage", "salami", "pepperoni", "prosciutto", "chorizo", "pancetta", "meat",
    "mince", "lard", "gelatin", "gelatine", "anchovy", "anchovies", "fish", "salmon", "tuna",
    "cod", "trout", "sardine", "sardines", "mackerel", "tilapia", "shrimp", "shrimps", "prawn",
    "prawns", "crab", "lobster", "clam", "clams", "mussel", "mussels", "oyster", "oysters",
    "squid", "octopus", "scallop", "scallops", "crayfish", "fish sauce", "oyster sauce",
    "worcestershire", "bonito", "dashi", "suet",
]
EGG = ["egg", "eggs", "egg white", "egg whites", "egg yolk", "yolk", "yolks", "mayonnaise", "meringue"]
DAIRY = [
    "milk", "butter", "cheese", "cream", "yogurt", "yoghurt", "ghee", "paneer", "ricotta",
    "mozzarella", "parmesan", "cheddar", "feta", "mascarpone", "buttermilk", "whey", "custard",
    "sour cream", "creme fraiche", "crème fraîche", "kefir", "brie", "gouda", "halloumi", "quark",
]
GLUTEN = [
    "flour", "wheat", "bread", "breadcrumb", "breadcrumbs", "panko", "pasta", "spaghetti", "penne",
    "macaroni", "lasagna", "noodle", "noodles", "couscous", "bulgur", "barley", "rye", "semolina",
    "seitan", "soy sauce", "beer", "cracker", "crackers", "tortilla", "tortillas", "pita", "bun",
    "buns", "croissant", "biscuit", "biscuits", "malt", "farro", "spelt", "orzo", "dumpling",
]
HIGH_CARB = [
    "sugar", "honey", "maple syrup", "syrup", "rice", "pasta", "spaghetti", "noodle", "noodles",
    "bread", "potato", "potatoes", "flour", "couscous", "tortilla", "tortillas",
]
KETO_EXTRA = ["bean", "beans", "lentil", "lentils", "chickpea", "chickpeas", "banana", "oat", "oats", "corn", "quinoa"]
PALEO = [
    "rice", "wheat", "flour", "pasta", "spaghetti", "bread", "oat", "oats", "corn", "quinoa",
    "bean", "beans", "lentil", "lentils", "chickpea", "chickpeas", "peanut", "peanuts", "soy",
    "tofu", "tempeh", "edamame", "sugar", "noodle", "noodles", *DAIRY,
]

RULES: dict[str, list[str]] = {
    "Vegan": MEAT_FISH + EGG + DAIRY + ["honey"],
    "Vegetarian": MEAT_FISH,
    "Dairy-Free": DAIRY,
    "Gluten-Free": GLUTEN,
    "Low-Carb": HIGH_CARB,
    "Keto": HIGH_CARB + KETO_EXTRA,
    "Paleo": PALEO,
}

# Phrases that look like a forbidden word but are fine. Removed before matching.
EXCEPTIONS = [
    "coconut milk", "coconut cream", "almond milk", "soy milk", "oat milk", "rice milk", "plant milk",
    "plant-based milk", "non-dairy milk", "peanut butter", "almond butter", "cocoa butter",
    "nut butter", "cream of tartar", "vegetable broth", "vegetable stock", "mushroom broth",
    "rice flour", "corn flour", "cornflour", "almond flour", "coconut flour", "chickpea flour",
    "gram flour", "buckwheat flour", "tapioca flour", "potato flour", "cassava flour", "oat flour",
    "millet flour", "sorghum flour", "teff flour", "rice noodle", "rice noodles", "corn tortilla",
    "corn tortillas", "tamari", "coconut aminos", "nutritional yeast", "breadfruit",
]
# A line marked like this is a substitute, never a violation for that diet.
SAFE_MARKERS = {
    "Vegan": ["vegan", "plant-based", "plant based", "meatless", "meat substitute", "egg replacer"],
    "Vegetarian": ["vegan", "vegetarian", "plant-based", "plant based", "meatless", "meat substitute"],
    "Dairy-Free": ["vegan", "dairy-free", "dairy free", "plant-based", "non-dairy"],
    "Gluten-Free": ["gluten-free", "gluten free"],
    "Keto": ["sugar-free", "sugar free", "keto"],
    "Low-Carb": ["sugar-free", "sugar free", "low-carb", "low carb", "keto"],
    "Paleo": ["sweet potato", "paleo"],
}


def _clean(line: str, diet: str) -> str | None:
    text = line.lower()
    if any(m in text for m in SAFE_MARKERS.get(diet, [])):
        return None
    for phrase in sorted(EXCEPTIONS, key=len, reverse=True):
        text = text.replace(phrase, " ")
    return text


def violations(lines: list[str], diet: str) -> list[str]:
    """Ingredient lines that clearly break the diet, each with the word that triggered it."""
    words = RULES.get(diet)
    if not words:
        return []
    pattern = re.compile(r"\b(" + "|".join(re.escape(w) for w in sorted(set(words), key=len, reverse=True)) + r")\b")
    found = []
    for line in lines:
        text = _clean(line, diet)
        if text and (m := pattern.search(text)):
            found.append(f'"{line}" ({m.group(1)})')
    return found
