import re
from datetime import date, timedelta

import httpx

from app.config import settings

BASE = settings.mealie_url.rstrip("/")
HEADERS = {"Authorization": f"Bearer {settings.mealie_api_key}"}


def _tag(name: str) -> dict:
    slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
    return {"name": name, "slug": slug}


def _get(path: str, params: dict = None) -> dict:
    r = httpx.get(f"{BASE}{path}", headers=HEADERS, params=params, timeout=15)
    r.raise_for_status()
    return r.json()


def _post(path: str, body) -> dict:
    r = httpx.post(f"{BASE}{path}", headers=HEADERS, json=body, timeout=15)
    r.raise_for_status()
    return r.json() if r.content else {}


def _put(path: str, body: dict) -> dict:
    r = httpx.put(f"{BASE}{path}", headers=HEADERS, json=body, timeout=15)
    if not r.is_success:
        print(f"PUT {path} {r.status_code}: {r.text[:500]}")
    r.raise_for_status()
    return r.json() if r.content else {}



# ── existing recipes ──────────────────────────────────────────────────────────

def fetch_all_recipes() -> list[dict]:
    page, per_page = 1, 50
    results = []
    while True:
        data = _get("/api/recipes", params={"page": page, "perPage": per_page})
        items = data.get("items", [])
        results.extend(items)
        if len(items) < per_page:
            break
        page += 1
    return results


def fetch_recipe_detail(slug: str) -> dict:
    return _get(f"/api/recipes/{slug}")


# ── create recipes ────────────────────────────────────────────────────────────

def _format_recipe(recipe: dict) -> dict:
    """Convert generated recipe dict to Mealie's PUT schema."""
    ingredients = []
    for ing in recipe.get("recipeIngredient", []):
        if isinstance(ing, str):
            ingredients.append({"note": ing, "display": ing, "quantity": 0,
                                 "unit": None, "food": None, "title": None, "originalText": ing})
        elif isinstance(ing, dict):
            ingredients.append(ing)

    instructions = []
    for step in recipe.get("recipeInstructions", []):
        if isinstance(step, str):
            instructions.append({"text": step, "title": "", "summary": "", "ingredientReferences": []})
        elif isinstance(step, dict):
            instructions.append({"text": step.get("text", ""), "title": step.get("title", ""),
                                  "summary": step.get("summary", ""), "ingredientReferences": []})

    return {
        "name": recipe.get("name", ""),
        "description": recipe.get("description", ""),
        "recipeYield": recipe.get("recipeYield", ""),
        "totalTime": recipe.get("totalTime") or None,
        "prepTime": recipe.get("prepTime") or None,
        "performTime": recipe.get("performTime") or None,
        "recipeIngredient": ingredients,
        "recipeInstructions": instructions,
        "notes": recipe.get("notes", []),
        "orgURL": recipe.get("orgURL") or None,
        "tags": [_tag(t) if isinstance(t, str) else t for t in recipe.get("tags", [])],
    }


def add_tags_to_recipe(slug: str, tags: list[str]) -> None:
    detail = _get(f"/api/recipes/{slug}")
    existing = [t["name"] for t in detail.get("tags", [])]
    merged = list(dict.fromkeys(existing + tags))
    body = _format_recipe(detail)
    body["tags"] = [_tag(t) for t in merged]
    _put(f"/api/recipes/{slug}", body)


def create_recipe(recipe: dict) -> tuple[str, str]:
    """Create or update a recipe in Mealie (upsert by name). Returns (slug, id)."""
    # Find existing recipe with this name to avoid creating duplicate shells
    all_recipes = fetch_all_recipes()
    existing = next(
        (r for r in all_recipes if r.get("name", "").lower() == recipe["name"].lower()),
        None,
    )
    if existing:
        slug = existing["slug"]
    else:
        result = _post("/api/recipes", {"name": recipe["name"]})
        slug = result if isinstance(result, str) else result.get("slug", recipe["name"])
    _put(f"/api/recipes/{slug}", _format_recipe(recipe))
    detail = _get(f"/api/recipes/{slug}")
    return slug, detail["id"]


# ── meal plan ─────────────────────────────────────────────────────────────────

def add_to_mealplan(recipe_id: str, plan_date: str, entry_type: str = "dinner") -> dict:
    return _post("/api/households/mealplans", {
        "date": plan_date,
        "entryType": entry_type,
        "recipeId": recipe_id,
        "title": "",
    })


def week_dates(start: date = None, count: int = 7) -> list[str]:
    """Return ISO date strings for the next `count` days starting from start (default: today)."""
    start = start or date.today()
    return [(start + timedelta(days=i)).isoformat() for i in range(count)]


# ── shopping list ─────────────────────────────────────────────────────────────

def create_shopping_list(name: str) -> str:
    """Create a shopping list and return its id."""
    result = _post("/api/households/shopping/lists", {"name": name})
    return result["id"]


def add_shopping_items(list_id: str, items: list[str]) -> None:
    for item in items:
        try:
            _post("/api/households/shopping/items", {
                "note": item, "quantity": 0, "isFood": False, "shoppingListId": list_id
            })
        except Exception as e:
            print(f"Shopping item error ({item!r}): {e}")
