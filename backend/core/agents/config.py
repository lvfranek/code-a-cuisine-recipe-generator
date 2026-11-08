"""Agent and task definitions for the recipe workflow.

- Every agent has a role, a goal and a backstory (one config dict per agent).
- Every task has a description (bullet list), an expected_output and an agent.
- Prompts are always built by the helpers below, so all agents stay consistent.

Placeholders like {count} are filled with `fill()` (plain replace, so JSON
braces in the text need no escaping).
"""

AGENTS: dict[str, dict[str, str]] = {
    "input_agent": {
        "role": "Ingredient Analyst",
        "goal": "Turn the user's ingredient list into clean English search terms.",
        "backstory": (
            "You have worked in kitchens all over the world and know ingredient names in many "
            "languages. You are precise and never add ingredients that are not in the list."
        ),
    },
    "chef_agent": {
        "role": "Recipe Developer",
        "goal": "Turn real recipes into dishes the user can cook with what they have.",
        "backstory": (
            "You are a professional recipe developer who writes clear, friendly recipes for "
            "beginners. You respect dietary rules strictly and never invent ingredients the user "
            "does not have beyond common pantry staples. You always answer with valid JSON."
        ),
    },
    "diet_checker": {
        "role": "Diet Inspector",
        "goal": "Find ingredients that break the user's dietary requirements.",
        "backstory": (
            "You are a strict but fair dietitian. You know hidden animal products and hidden "
            "gluten in everyday ingredients. You only report clear violations, never matters of taste."
        ),
    },
    "nutrition_agent": {
        "role": "Nutrition Analyst",
        "goal": "Turn recipe ingredient lines into food names and weights in grams.",
        "backstory": (
            "You are a food scientist who knows typical weights of kitchen measures and ingredients. "
            "You never calculate calories yourself; you only measure."
        ),
    },
}

INSTRUCTION_RULES = [
    "Instructions: 6 to 10 steps, each 1 to 3 full sentences.",
    "Explain each step plainly, the way you would tell a grandparent who is new to cooking: "
    "what to do, what it should look, smell or feel like, and roughly how long it takes.",
    "Use simple everyday words. No chef jargon, no abbreviations.",
    "Do NOT put the recipe name, cuisine or serving count inside any step, and do NOT number the steps.",
]

RECIPE_OUTPUT = (
    'ONLY a JSON object, no markdown: {"recipes": [recipe, ...]} with exactly {count} recipes.\n'
    "Nutrition values are per portion, in grams except calories (kcal).\n"
    "Each recipe looks exactly like this example (shortened to 2 steps here):\n{example}"
)

TASKS: dict[str, dict] = {
    "normalize_ingredients": {
        "agent": "input_agent",
        "description": [
            "Translate every ingredient to its common English name (the user may write German or other languages).",
            'Use lowercase and singular ("Kartoffeln" -> "potato", "Tomatoes" -> "tomato").',
            "Fix obvious typos. Keep useful detail (\"chicken breast\" stays \"chicken breast\").",
            'Split combined entries ("salt and pepper" -> "salt", "pepper"). Drop entries that are not food.',
            "Never add ingredients that are not in the list.",
        ],
        "expected_output": 'ONLY a JSON object, no markdown: {"ingredients": ["potato", "chicken breast", ...]}',
    },
    "adapt_recipes": {
        "agent": "chef_agent",
        "description": [
            "Pick the {count} best candidates for this user, all different dishes, and adapt each one.",
            "Prefer candidates that use many of the user's ingredients and are real meals or dishes; "
            "avoid basics like stocks, plain sauces, pickles or drinks unless nothing else fits.",
            "Keep the character of the original dish, but cook it with the user's ingredients.",
            "Main ingredients must come from the user's list or common pantry staples "
            "(salt, pepper, oil, water, basic spices). Replace or leave out what the user does not have.",
            "Respect every dietary requirement strictly; replace ingredients that break it.",
            "Scale amounts to the requested portions and aim for the target cooking time.",
            "You may rename the dish to reflect your changes.",
            "Write everything in English, also when the user's ingredients are in another language "
            "(use the English search terms given).",
            "Every recipe must be a complete dish built around the user's main ingredients.",
            "dietTags: only tags that the adapted recipe really satisfies.",
            "nutrition: your best estimate per portion.",
            "basedOnId: the id in [brackets] of the candidate you adapted. Use each candidate at most once.",
            *INSTRUCTION_RULES,
        ],
        "expected_output": RECIPE_OUTPUT,
    },
    "create_recipes": {
        "agent": "chef_agent",
        "description": [
            "Create {count} distinct recipes that primarily use the user's ingredients.",
            "Write everything in English, also when the user's ingredients are in another language "
            "(use the English search terms given).",
            "Common pantry staples (salt, pepper, oil, water, basic spices) may be assumed.",
            "Respect every dietary requirement strictly.",
            "Scale amounts to the requested portions and aim for the target cooking time.",
            *INSTRUCTION_RULES,
        ],
        "expected_output": RECIPE_OUTPUT,
    },
}


DIET_DEFINITIONS = {
    "Vegan": "no animal products at all: no meat, fish, seafood, eggs, dairy, honey or gelatin.",
    "Vegetarian": "no meat, poultry, fish, seafood or gelatin. Eggs and dairy are allowed.",
    "Gluten-Free": "no wheat, barley, rye or spelt, and nothing made from them (bread, pasta, flour, "
    "regular soy sauce, most stock cubes, beer). Dairy, eggs, meat, rice and corn are allowed.",
    "Dairy-Free": "no milk products (milk, butter, cheese, cream, yogurt, ghee). Eggs are allowed.",
    "Keto": "very low carb: no sugar, honey, grains, bread, pasta, rice, potatoes, legumes or sweet fruit. "
    "Meat, fish, eggs, dairy, butter, oils and low-carb vegetables are allowed.",
    "Low-Carb": "no sugar and no larger amounts of bread, pasta, rice or potatoes. Dairy, meat and eggs are allowed.",
    "Paleo": "no grains, legumes (incl. peanuts, soy), dairy or refined sugar. Meat, fish, eggs, "
    "vegetables, fruit, nuts and honey are allowed.",
}

TASKS["check_diets"] = {
    "agent": "diet_checker",
    "description": [
        "Check every recipe against ALL required diets: {diets}.",
        "Use exactly these definitions:\n{definitions}",
        "Report an issue only under the diet it really breaks by the definition above.",
        "Look for hidden problems too: Worcestershire sauce contains anchovy, regular soy sauce and most "
        "stock cubes contain wheat, gelatin is animal-based, honey is not vegan, butter and ghee are dairy. "
        "Ignore animal rennet in cheese.",
        "Only report clear violations. If an ingredient is fine or you are unsure, do not report it.",
        "Ignore taste, style and missing ingredients.",
    ],
    "expected_output": (
        'ONLY a JSON object, no markdown: {"recipes": [{"index": 1, "problems": '
        '[{"diet": "Vegan", "issue": "contains honey"}]}, {"index": 2, "problems": []}]}. '
        "One entry per recipe, index as given, diet must be one of the required diets."
    ),
}

TASKS["measure_ingredients"] = {
    "agent": "nutrition_agent",
    "description": [
        "For every ingredient line of every recipe, give the generic English food name as in a nutrition "
        'database ("chicken breast", "olive oil", "tomato", "cheddar cheese") and its weight in grams '
        "for the WHOLE recipe.",
        "Use uncooked weights. Typical conversions: 1 tbsp = 15 g (oil 14 g), 1 tsp = 5 g, "
        "1 cup liquid = 240 g, 1 cup flour = 125 g, 1 cup uncooked rice = 185 g, 1 medium onion = 110 g, "
        "1 egg = 50 g, 1 clove garlic = 3 g, 1 medium potato = 170 g, 1 medium tomato = 120 g.",
        "Salt, pepper and spices 'to taste' or 'a pinch' = 1 g. Water = 0 g.",
        "If a line lists alternatives, use the first one.",
    ],
    "expected_output": (
        'ONLY a JSON object, no markdown: {"recipes": [{"index": 1, "items": '
        '[{"food": "tomato", "grams": 240}, {"food": "olive oil", "grams": 28}]}]}. '
        "One entry per recipe, index as given."
    ),
}


def fill(text: str, **values) -> str:
    for key, value in values.items():
        text = text.replace("{" + key + "}", str(value))
    return text


def build_system_prompt(agent_key: str) -> str:
    agent = AGENTS[agent_key]
    return f"You are the {agent['role']}.\nGoal: {agent['goal']}\n{agent['backstory']}"


def build_task_prompt(task_key: str, context: str, **values) -> str:
    task = TASKS[task_key]
    bullets = "\n".join(f"- {fill(line, **values)}" for line in task["description"])
    return "\n\n".join([
        f"Task:\n{bullets}",
        context,
        f"Expected output:\n{fill(task['expected_output'], **values)}",
    ])


def build_messages(task_key: str, context: str, **values) -> list[dict]:
    """System prompt from the task's agent + user prompt from the task."""
    agent_key = TASKS[task_key]["agent"]
    return [
        {"role": "system", "content": build_system_prompt(agent_key)},
        {"role": "user", "content": build_task_prompt(task_key, context, **values)},
    ]
