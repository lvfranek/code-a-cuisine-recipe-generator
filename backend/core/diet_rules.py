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
    "bean", "beans", "lentil", "lentils", "chickpea", "chickpeas", "peanut", "peanuts", "soy", "soy sauce",
    "tofu", "tempeh", "edamame", "sugar", "noodle", "noodles", *DAIRY,
]

# Ready-made products that usually contain a hidden non-compliant ingredient.
# They count as a violation unless the line names a compliant version
# ("vegan pesto", "gluten-free stock cube" -> SAFE_MARKERS).
HIDDEN_ANIMAL = [
    "pesto", "kimchi", "marshmallow", "marshmallows", "caesar dressing", "gummy bears", "gummies",
    "jelly sweets", "shrimp paste", "anchovy paste", "beef stock", "chicken stock", "stock cube",
    "bouillon cube", "bouillon", "parmesan",
]
HIDDEN_DAIRY = ["pesto", "ranch dressing", "caesar dressing", "milk chocolate", "naan"]
HIDDEN_GLUTEN = [
    "stock cube", "bouillon cube", "bouillon", "naan", "croutons", "teriyaki sauce", "hoisin sauce",
    "malt vinegar", "seitan", "panko", "breadcrumbs",
]

RULES: dict[str, list[str]] = {
    "Vegan": MEAT_FISH + EGG + DAIRY + ["honey"] + HIDDEN_ANIMAL + HIDDEN_DAIRY,
    "Vegetarian": MEAT_FISH + [w for w in HIDDEN_ANIMAL if w != "parmesan"],
    "Dairy-Free": DAIRY + HIDDEN_DAIRY,
    "Gluten-Free": GLUTEN + HIDDEN_GLUTEN,
    "Low-Carb": HIGH_CARB,
    "Keto": HIGH_CARB + KETO_EXTRA,
    "Paleo": PALEO,
}

# Phrases that look like a forbidden word but are fine. Removed before matching.
# Some are fine for every diet, others only for some ("rice noodles" are
# gluten-free, but not keto).
_PLANT_MILKS = [
    "coconut milk", "coconut cream", "almond milk", "soy milk", "oat milk", "rice milk", "cashew milk",
    "plant milk", "plant-based milk", "non-dairy milk", "peanut butter", "almond butter", "cashew butter",
    "cocoa butter", "nut butter", "sunflower butter", "coconut yogurt", "vegan butter", "vegan cheese",
]
_GLUTEN_FREE_GRAINS = [
    "rice flour", "corn flour", "cornflour", "chickpea flour", "gram flour", "buckwheat flour",
    "tapioca flour", "potato flour", "cassava flour", "millet flour", "sorghum flour", "teff flour",
    "rice noodle", "rice noodles", "corn tortilla", "corn tortillas", "tamari", "buckwheat noodles",
]
_LOW_CARB_SWAPS = [
    "zucchini noodles", "zucchini noodle", "zoodles", "vegetable noodles", "veggie noodles", "into noodles",
    "cauliflower rice", "riced cauliflower", "cauliflower mash", "lettuce wrap", "lettuce wraps",
    "shirataki noodles", "konjac noodles", "almond flour", "coconut flour",
]
_ALWAYS_FINE = [
    "cream of tartar", "vegetable broth", "vegetable stock", "mushroom broth", "coconut aminos",
    "nutritional yeast", "breadfruit", "eggplant",
]
EXCEPTIONS: dict[str, list[str]] = {
    "Vegan": _ALWAYS_FINE + _PLANT_MILKS + _LOW_CARB_SWAPS,
    "Vegetarian": _ALWAYS_FINE + _LOW_CARB_SWAPS,
    "Dairy-Free": _ALWAYS_FINE + _PLANT_MILKS + _LOW_CARB_SWAPS,
    "Gluten-Free": _ALWAYS_FINE + _GLUTEN_FREE_GRAINS + _LOW_CARB_SWAPS,
    "Keto": _ALWAYS_FINE + _LOW_CARB_SWAPS + ["tamari"],
    "Low-Carb": _ALWAYS_FINE + _LOW_CARB_SWAPS + ["tamari"],
    "Paleo": _ALWAYS_FINE + ["coconut milk", "coconut cream", "almond milk", "almond butter", "cashew butter",
                             "almond flour", "coconut flour", "cassava flour", "tapioca flour",
                             "cauliflower rice", "riced cauliflower", "zucchini noodles", "zoodles", "lettuce wraps"],
}

# "olive oil (instead of butter)", "maple syrup to replace honey": the forbidden
# word is only mentioned as the thing that was replaced.
_REPLACED = re.compile(
    r"\(?\b(instead of|to replace|replacing|replaces|in place of|swap(ped)? for|substitute for|no)\b[^,;()]*\)?",
    re.IGNORECASE,
)
# "milk (oat or soy)", "butter (vegan)": the bracket says it is a plant version.
_PLANT_QUALIFIED = re.compile(
    r"\b(milk|butter|cheese|yogurt|cream)\s*\([^)]*\b(oat|soy|almond|coconut|rice|cashew|plant|vegan|non-dairy|dairy-free)\b[^)]*\)",
    re.IGNORECASE,
)

# A line marked like this is a substitute, never a violation for that diet.
SAFE_MARKERS = {
    "Vegan": ["vegan", "plant-based", "plant based", "meatless", "meat substitute", "egg replacer"],
    "Vegetarian": ["vegan", "vegetarian", "plant-based", "plant based", "meatless", "meat substitute",
                   "vegetable stock", "vegetable bouillon", "gelatin-free", "gelatine-free"],
    "Dairy-Free": ["vegan", "dairy-free", "dairy free", "plant-based", "non-dairy"],
    "Gluten-Free": ["gluten-free", "gluten free"],
    "Keto": ["sugar-free", "sugar free", "keto"],
    "Low-Carb": ["sugar-free", "sugar free", "low-carb", "low carb", "keto"],
    "Paleo": ["sweet potato", "paleo"],
}


def _clean(line: str, diet: str) -> str | None:
    text = _REPLACED.sub(" ", line.lower())
    if diet in ("Vegan", "Dairy-Free"):
        text = _PLANT_QUALIFIED.sub(" ", text)
    if any(m in text for m in SAFE_MARKERS.get(diet, [])):
        return None
    for phrase in sorted(EXCEPTIONS.get(diet, _ALWAYS_FINE), key=len, reverse=True):
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


# Ingredients that are explicitly fine for a diet. Used to drop false alarms of
# the LLM critic (e.g. "honey breaks Vegetarian").
ALLOWED: dict[str, list[str]] = {
    "Vegetarian": ["honey", "egg", "eggs", "milk", "butter", "cheese", "cream", "yogurt", "yoghurt", "dairy", "ghee"],
    "Gluten-Free": ["dairy", "milk", "butter", "cheese", "cream", "egg", "eggs", "rice", "corn", "potato", "meat", "honey"],
    "Dairy-Free": ["egg", "eggs", "honey", "coconut milk", "almond milk", "oat milk", "soy milk"],
    "Keto": ["butter", "cheese", "cream", "dairy", "egg", "eggs", "meat", "bacon", "oil"],
    "Low-Carb": ["butter", "cheese", "cream", "dairy", "egg", "eggs", "meat", "bacon", "oil"],
    "Paleo": ["honey", "egg", "eggs", "meat", "fish", "sweet potato"],
}


def is_false_alarm(diet: str, issue: str) -> bool:
    """True if the issue only names ingredients that the diet allows."""
    text = issue.lower()
    allowed = ALLOWED.get(diet, [])
    if not any(re.search(rf"\b{re.escape(a)}\b", text) for a in allowed):
        return False
    forbidden = RULES.get(diet, [])
    for a in sorted(allowed, key=len, reverse=True):
        text = re.sub(rf"\b{re.escape(a)}\b", " ", text)
    return not any(re.search(rf"\b{re.escape(w)}\b", text) for w in forbidden)


# Substitute ideas for the chef when a user's ingredient breaks the diet.
_GRAINS = {"pasta", "spaghetti", "penne", "macaroni", "noodle", "noodles", "bread", "flour", "tortilla", "tortillas",
           "rice", "couscous", "bun", "buns", "pita", "oat", "oats", "corn"}
_SUBSTITUTES = {
    "pesto": "a vegan pesto, or basil blended with olive oil and nuts",
    "kimchi": "vegan kimchi (without fish sauce)",
    "marshmallow": "vegan (gelatin-free) marshmallows",
    "marshmallows": "vegan (gelatin-free) marshmallows",
    "caesar dressing": "a lemon, olive oil and mustard dressing",
    "stock cube": "a vegetable or gluten-free stock cube",
    "bouillon cube": "a vegetable or gluten-free stock cube",
    "bouillon": "a vegetable or gluten-free stock",
    "naan": "corn tortillas or rice",
    "croutons": "toasted nuts or seeds",
    "teriyaki sauce": "tamari with a little maple syrup",
    "hoisin sauce": "tamari with a little maple syrup",
    "parmesan": "nutritional yeast",
    "honey": "maple syrup or agave syrup",
    "butter": "olive oil or vegan butter",
    "ghee": "olive oil",
    "milk": "oat milk or soy milk",
    "cream": "coconut cream",
    "sour cream": "coconut yogurt",
    "yogurt": "coconut yogurt",
    "yoghurt": "coconut yogurt",
    "egg": "leave it out (or a flax egg for baking)",
    "eggs": "leave them out (or flax eggs for baking)",
    "mayonnaise": "vegan mayonnaise or olive oil",
    "bacon": "smoked paprika for the smoky taste",
    "chicken": "vegetable broth / more vegetables",
    "fish sauce": "salt and a little lime juice",
    "worcestershire": "a little vinegar",
    "sugar": "leave it out",
    "potato": "cauliflower",
    "potatoes": "cauliflower",
    "peanut": "cashews or almonds",
    "peanuts": "cashews or almonds",
    "bean": "more vegetables",
    "beans": "more vegetables",
    "tofu": "chicken or more vegetables",
}


def substitute_for(diet: str, word: str) -> str:
    if word in _SUBSTITUTES and not (word == "chicken" and diet not in ("Vegetarian", "Vegan")):
        return _SUBSTITUTES[word]
    if word == "soy sauce":
        return "coconut aminos" if diet == "Paleo" else "tamari (gluten-free soy sauce)"
    if word in _GRAINS:
        if diet == "Gluten-Free":
            return "a gluten-free version (rice noodles, gluten-free pasta or bread, corn tortillas, rice flour)"
        return "low-carb vegetables (zucchini noodles, cauliflower rice, lettuce wraps)"
    if word in DAIRY:
        return "leave it out (or nutritional yeast for a cheesy taste)"
    if word in MEAT_FISH:
        return "leave it out or use more vegetables"
    return "leave it out"


def conflicts(ingredient_names: list[str], diets: list[str]) -> list[str]:
    """User ingredients that break a required diet, with a substitute idea for each.
    Told to the chef BEFORE cooking, so recipes are compliant on the first try."""
    out = []
    for diet in diets:
        words = RULES.get(diet)
        if not words:
            continue
        pattern = re.compile(r"\b(" + "|".join(re.escape(w) for w in sorted(set(words), key=len, reverse=True)) + r")\b")
        for name in ingredient_names:
            text = _clean(name, diet)
            if text and (m := pattern.search(text)):
                out.append(f'"{name}" breaks {diet}: do not use it; instead use {substitute_for(diet, m.group(1))}')
    return out
