from datetime import date, timedelta

import httpx

from app.config import settings

BASE = settings.mealie_url.rstrip("/")
HEADERS = {"Authorization": f"Bearer {settings.mealie_api_key}"}


def _get(path: str, params: dict = None) -> dict:
    r = httpx.get(f"{BASE}{path}", headers=HEADERS, params=params, timeout=15)
    r.raise_for_status()
    return r.json()


def _post(path: str, body: dict) -> dict:
    r = httpx.post(f"{BASE}{path}", headers=HEADERS, json=body, timeout=15)
    r.raise_for_status()
    return r.json()


def _put(path: str, body: dict) -> dict:
    r = httpx.put(f"{BASE}{path}", headers=HEADERS, json=body, timeout=15)
    r.raise_for_status()
    return r.json()


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

def create_recipe(recipe: dict) -> tuple[str, str]:
    """Create a recipe in Mealie. Returns (slug, id)."""
    result = _post("/api/recipes", {"name": recipe["name"]})
    slug = result if isinstance(result, str) else result.get("slug", recipe["name"])
    _put(f"/api/recipes/{slug}", recipe)
    detail = _get(f"/api/recipes/{slug}")
    return slug, detail["id"]


# ── meal plan ─────────────────────────────────────────────────────────────────

def add_to_mealplan(recipe_id: str, plan_date: str, entry_type: str = "dinner") -> dict:
    return _post("/api/groups/mealplans", {
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
    result = _post("/api/groups/shopping/lists", {"name": name})
    return result["id"]


def add_shopping_items(list_id: str, items: list[str]) -> None:
    payload = [{"note": item, "quantity": 0, "isFood": False} for item in items]
    _post(f"/api/groups/shopping/lists/{list_id}/items", payload)
