import json

import anthropic

from app.config import settings

client = anthropic.Anthropic(api_key=settings.anthropic_api_key)


def generate_recipes(
    sale_items: list[dict],
    existing_recipe_names: list[str],
    count: int = 3,
) -> list[dict]:
    """
    Generate new recipes using sale items, avoiding duplicates with existing recipes.
    Returns a list of Mealie-compatible recipe dicts.
    """
    sale_summary = "\n".join(
        f"- {item['name']} ({item['price']}{', ' + item['unit'] if item['unit'] else ''})"
        for item in sale_items
    )
    existing = ", ".join(existing_recipe_names) if existing_recipe_names else "none"

    prompt = f"""You are a meal planning assistant. Generate {count} recipes that use as many of these on-sale grocery items as possible.

On-sale items this week:
{sale_summary}

Already covered by existing recipes (avoid duplicates): {existing}

Return a JSON array of {count} recipes. Each recipe must have exactly these fields:
- name (string)
- description (string, 1-2 sentences)
- recipeYield (string, e.g. "4 servings")
- prepTime (string, ISO 8601 duration, e.g. "PT15M")
- performTime (string, ISO 8601 duration, e.g. "PT30M")
- totalTime (string, ISO 8601 duration)
- recipeIngredient (array of strings, e.g. ["1 lb chicken breast", "2 cloves garlic"])
- recipeInstructions (array of objects with "text" field, e.g. [{{"text": "Preheat oven to 375F."}}])
- tags (array of strings, e.g. ["weeknight", "budget-friendly"])
- orgURL (empty string)
- notes (array of objects with "title" and "text" fields — include one note listing which sale items were used)

Return ONLY the JSON array, no other text."""

    response = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=8192,
        messages=[{"role": "user", "content": prompt}],
    )

    raw = response.content[0].text.strip()
    if raw.startswith("```"):
        raw = raw.split("```")[1]
        if raw.startswith("json"):
            raw = raw[4:]
    return json.loads(raw.strip())
