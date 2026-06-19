import json
import os
import re
from html import escape

from app.config import settings


def _slugify(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")


def _schema_org_recipe(recipe: dict) -> dict:
    """Map our generated-recipe shape to schema.org/Recipe JSON-LD for recipe-scrapers."""
    instructions = []
    for step in recipe.get("recipeInstructions", []):
        text = step.get("text", "") if isinstance(step, dict) else str(step)
        instructions.append({"@type": "HowToStep", "text": text})

    return {
        "@context": "https://schema.org",
        "@type": "Recipe",
        "name": recipe.get("name", ""),
        "description": recipe.get("description", ""),
        "recipeYield": recipe.get("recipeYield", ""),
        "prepTime": recipe.get("prepTime") or None,
        "cookTime": recipe.get("performTime") or None,
        "totalTime": recipe.get("totalTime") or None,
        "recipeIngredient": [
            ing if isinstance(ing, str) else ing.get("originalText", "")
            for ing in recipe.get("recipeIngredient", [])
        ],
        "recipeInstructions": instructions,
        "keywords": ", ".join(
            t if isinstance(t, str) else t.get("name", "") for t in recipe.get("tags", [])
        ),
    }


def render_recipe_html(recipe: dict) -> str:
    """Render a standalone HTML page embedding schema.org/Recipe JSON-LD."""
    jsonld = json.dumps(_schema_org_recipe(recipe), indent=2)
    name = escape(recipe.get("name", "Untitled Recipe"))
    description = escape(recipe.get("description", ""))
    ingredients = "".join(
        f"<li>{escape(i if isinstance(i, str) else i.get('originalText', ''))}</li>"
        for i in recipe.get("recipeIngredient", [])
    )
    steps = "".join(
        f"<li>{escape(s.get('text', '') if isinstance(s, dict) else str(s))}</li>"
        for s in recipe.get("recipeInstructions", [])
    )

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>{name}</title>
<script type="application/ld+json">
{jsonld}
</script>
</head>
<body>
<h1>{name}</h1>
<p>{description}</p>
<h2>Ingredients</h2>
<ul>{ingredients}</ul>
<h2>Instructions</h2>
<ol>{steps}</ol>
</body>
</html>"""


def write_recipe_page(recipe: dict) -> tuple[str, str]:
    """Render and write a recipe page to disk. Returns (slug, public_url)."""
    slug = _slugify(recipe.get("name", "recipe"))
    os.makedirs(settings.recipe_pages_dir, exist_ok=True)
    path = os.path.join(settings.recipe_pages_dir, f"{slug}.html")
    with open(path, "w", encoding="utf-8") as f:
        f.write(render_recipe_html(recipe))

    base = settings.public_base_url.rstrip("/")
    url = f"{base}/recipes/{slug}.html"
    return slug, url
