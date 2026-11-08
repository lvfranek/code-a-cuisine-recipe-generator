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
            "Common pantry staples (salt, pepper, oil, water, basic spices) may be assumed.",
            "Respect every dietary requirement strictly.",
            "Scale amounts to the requested portions and aim for the target cooking time.",
            *INSTRUCTION_RULES,
        ],
        "expected_output": RECIPE_OUTPUT,
    },
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
