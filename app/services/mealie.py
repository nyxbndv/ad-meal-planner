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


def _post(path: str, body: dict, timeout: float = 15) -> dict:
    r = httpx.post(f"{BASE}{path}", headers=HEADERS, json=body, timeout=timeout)
    if not r.is_success:
        print(f"POST {path} {r.status_code}: {r.text[:500]}")
    r.raise_for_status()
    return r.json() if r.content else {}


def _delete(path: str) -> None:
    r = httpx.delete(f"{BASE}{path}", headers=HEADERS, timeout=15)
    r.raise_for_status()


def _patch(path: str, body: dict) -> dict:
    r = httpx.patch(f"{BASE}{path}", headers=HEADERS, json=body, timeout=15)
    if not r.is_success:
        print(f"PATCH {path} {r.status_code}: {r.text[:500]}")
    r.raise_for_status()
    return r.json() if r.content else {}


# ── existing recipes ──────────────────────────────────────────────────────────

def fetch_all_recipes() -> list[dict]:
    data = _get("/api/recipes", params={"page": 1, "perPage": -1})
    return data.get("data") or data.get("items") or []


def _normalize(recipe: dict) -> dict:
    """Flatten Mealie's ingredient objects to plain strings for the matcher/shopping list."""
    recipe["recipeIngredient"] = [
        ing.get("display") or ing.get("note") or ing.get("originalText", "")
        for ing in recipe.get("recipeIngredient", [])
    ]
    return recipe


def fetch_recipe_detail(slug: str) -> dict:
    return _normalize(_get(f"/api/recipes/{slug}"))


# ── create recipes via URL import ─────────────────────────────────────────────
# Uses Mealie's recipe-scrapers-based URL importer instead of the recipe CRUD
# API, which has a broken name-uniqueness check on PUT in this Mealie version.

def create_recipe_from_url(url: str) -> tuple[str, str]:
    """Import a recipe by scraping `url` (our own generated HTML page with
    schema.org/Recipe JSON-LD). Deletes any existing recipe with the same
    name first so re-running a plan doesn't pile up duplicates."""
    result = _post("/api/recipes/create/url", {"url": url, "includeTags": True}, timeout=30)
    slug = result if isinstance(result, str) else result.get("slug")
    detail = _get(f"/api/recipes/{slug}")

    for r in fetch_all_recipes():
        if r["slug"] != slug and r.get("name", "").lower().strip() == detail.get("name", "").lower().strip():
            try:
                _delete(f"/api/recipes/{r['slug']}")
            except Exception as e:
                print(f"Failed to delete duplicate {r['slug']}: {e}")

    return slug, detail["id"]


def add_tags_to_recipe(slug: str, tags: list[str]) -> tuple[str, str]:
    """Tag an existing recipe via PATCH (name omitted, so this avoids the
    PUT name-uniqueness bug entirely)."""
    detail = _get(f"/api/recipes/{slug}")
    existing_tags = list(detail.get("tags", []))
    existing_names = {t["name"].lower() for t in existing_tags}
    new_tags = [_tag(t) for t in tags if t.lower() not in existing_names]
    _patch(f"/api/recipes/{slug}", {"tags": existing_tags + new_tags})
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
    start = start or date.today()
    return [(start + timedelta(days=i)).isoformat() for i in range(count)]


# ── shopping list ─────────────────────────────────────────────────────────────

def create_shopping_list(name: str) -> str:
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


def debug_mealie() -> dict:
    raw = _get("/api/recipes", params={"page": 1, "perPage": 5})
    return {"top_level_keys": list(raw.keys()), "sample": raw}
