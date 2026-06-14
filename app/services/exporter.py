import io
import json
import re
import zipfile


def _slugify(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")


def _mealie_recipe(recipe: dict) -> dict:
    """Normalize a recipe dict to Mealie's importable JSON schema."""
    return {
        "name": recipe.get("name", "Untitled Recipe"),
        "description": recipe.get("description", ""),
        "recipeYield": recipe.get("recipeYield", ""),
        "prepTime": recipe.get("prepTime", ""),
        "performTime": recipe.get("performTime", ""),
        "totalTime": recipe.get("totalTime", ""),
        "recipeIngredient": recipe.get("recipeIngredient", []),
        "recipeInstructions": recipe.get("recipeInstructions", []),
        "tags": recipe.get("tags", []),
        "orgURL": recipe.get("orgURL", ""),
        "notes": recipe.get("notes", []),
    }


def build_export_zip(
    generated_recipes: list[dict],
    matched_recipes: list[dict],
    sale_items: list[dict],
) -> bytes:
    """
    Returns ZIP bytes containing:
    - one JSON file per generated recipe (Mealie-importable)
    - a meal_plan.json with the weekly plan summary
    """
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for recipe in generated_recipes:
            slug = _slugify(recipe.get("name", "recipe"))
            data = _mealie_recipe(recipe)
            zf.writestr(f"recipes/{slug}.json", json.dumps(data, indent=2))

        plan = {
            "week_summary": {
                "sale_items_found": len(sale_items),
                "sale_items": sale_items,
                "existing_recipes_matched": [
                    {
                        "name": r.get("name"),
                        "slug": r.get("slug"),
                        "matched_sale_items": r.get("_matched_sales", []),
                    }
                    for r in matched_recipes
                ],
                "new_recipes_generated": [r.get("name") for r in generated_recipes],
            }
        }
        zf.writestr("meal_plan.json", json.dumps(plan, indent=2))

    return buf.getvalue()
