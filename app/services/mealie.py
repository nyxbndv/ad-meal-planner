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
    data = _get("/api/recipes", params={"page": 1, "perPage": -1})
    return data.get("data", [])


def fetch_recipe_detail(slug: str) -> dict:
    return _get(f"/api/recipes/{slug}")


def delete_duplicate_recipes() -> list[str]:
    """Delete duplicate recipes (same name, different slug). Returns list of deleted slugs."""
    all_recipes = fetch_all_recipes()
    by_name: dict[str, list[dict]] = {}
    for r in all_recipes:
        name = r.get("name", "").lower().strip()
        by_name.setdefault(name, []).append(r)

    deleted = []
    for name, dupes in by_name.items():
        if len(dupes) <= 1:
            continue
        # Keep the one whose slug best matches the canonical slug (no numeric suffix)
        canonical = _name_to_slug(dupes[0]["name"])
        dupes.sort(key=lambda r: (r["slug"] != canonical, r["slug"]))
        for r in dupes[1:]:
            try:
                httpx.delete(f"{BASE}/api/recipes/{r['slug']}", headers=HEADERS, timeout=15).raise_for_status()
                deleted.append(r["slug"])
                print(f"Deleted duplicate: {r['slug']} ({r.get('name')})")
            except Exception as e:
                print(f"Failed to delete {r['slug']}: {e}")
    return deleted


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
    existing_tags = [t["name"] for t in detail.get("tags", [])]
    merged = list(dict.fromkeys(existing_tags + tags))
    body = {**detail}
    body["tags"] = [_tag(t) for t in merged]
    _put(f"/api/recipes/{slug}", body)


def _name_to_slug(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")


def create_recipe(recipe: dict) -> tuple[str, str]:
    """Create or update a recipe in Mealie (upsert by slug). Returns (slug, id)."""
    expected_slug = _name_to_slug(recipe["name"])

    existing = None
    try:
        existing = _get(f"/api/recipes/{expected_slug}")
    except httpx.HTTPStatusError as e:
        if e.response.status_code != 404:
            raise

    if existing:
        slug = existing["slug"]
        stored_name = existing["name"]
    else:
        result = _post("/api/recipes", {"name": recipe["name"]})
        slug = result if isinstance(result, str) else result.get("slug", expected_slug)
        existing = _get(f"/api/recipes/{slug}")
        stored_name = existing["name"]

    # Merge generated content into the full Mealie object so all required
    # fields (id, slug, settings, nutrition, etc.) are preserved on PUT
    body = {**existing, **_format_recipe(recipe)}
    body["name"] = stored_name  # never let a name change trigger a slug conflict

    _put(f"/api/recipes/{slug}", body)
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
