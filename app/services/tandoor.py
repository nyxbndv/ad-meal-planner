import re
from datetime import date, timedelta

import httpx

from app.config import settings

BASE = settings.tandoor_url.rstrip("/")
HEADERS = {"Authorization": f"Token {settings.tandoor_api_key}"}


def _get(path: str, params: dict = None) -> dict:
    r = httpx.get(f"{BASE}{path}", headers=HEADERS, params=params, timeout=15)
    r.raise_for_status()
    return r.json()


def _post(path: str, body: dict) -> dict:
    r = httpx.post(f"{BASE}{path}", headers=HEADERS, json=body, timeout=15)
    if not r.is_success:
        print(f"POST {path} {r.status_code}: {r.text[:300]}")
    r.raise_for_status()
    return r.json() if r.content else {}


def _patch(path: str, body: dict) -> dict:
    r = httpx.patch(f"{BASE}{path}", headers=HEADERS, json=body, timeout=15)
    if not r.is_success:
        print(f"PATCH {path} {r.status_code}: {r.text[:300]}")
    r.raise_for_status()
    return r.json() if r.content else {}


def _delete(path: str) -> None:
    r = httpx.delete(f"{BASE}{path}", headers=HEADERS, timeout=15)
    r.raise_for_status()


def _parse_duration(iso: str | None) -> int:
    """ISO 8601 duration → minutes."""
    if not iso:
        return 0
    m = re.search(r"PT(?:(\d+)H)?(?:(\d+)M)?", iso)
    return (int(m.group(1) or 0) * 60 + int(m.group(2) or 0)) if m else 0


def _parse_servings(yield_str) -> int:
    m = re.search(r"\d+", str(yield_str or ""))
    return int(m.group()) if m else 4


def _normalize(recipe: dict) -> dict:
    """Add flat recipeIngredient list so the existing matcher works unchanged."""
    ingredients = []
    for step in recipe.get("steps", []):
        for ing in step.get("ingredients", []):
            food = ing.get("food")
            name = (food.get("name", "") if isinstance(food, dict) else "") or ing.get("original_text", "")
            if name:
                ingredients.append(name)
    recipe["recipeIngredient"] = ingredients
    return recipe


# ── recipes ────────────────────────────────────────────────────────────────────

def fetch_all_recipes() -> list[dict]:
    results, page = [], 1
    while True:
        data = _get("/api/recipe/", params={"page": page, "page_size": 100})
        batch = data.get("results", [])
        results.extend(batch)
        if not data.get("next"):
            break
        page += 1
    return results


def fetch_recipe_detail(recipe_id: int | str) -> dict:
    return _normalize(_get(f"/api/recipe/{recipe_id}/"))


def _get_or_create_keyword(name: str) -> dict:
    data = _get("/api/keyword/", params={"query": name, "page_size": 10})
    for kw in data.get("results", []):
        if kw["name"].lower() == name.lower():
            return kw
    return _post("/api/keyword/", {"name": name})


def create_recipe(recipe: dict) -> tuple[str, str]:
    """Create recipe in Tandoor. Deletes any existing recipe with the same name first."""
    name = recipe.get("name", "")
    name_lower = name.lower().strip()

    for r in fetch_all_recipes():
        if r.get("name", "").lower().strip() == name_lower:
            try:
                _delete(f"/api/recipe/{r['id']}/")
            except Exception as e:
                print(f"Failed to delete existing recipe {r['id']}: {e}")

    keywords = []
    for tag in recipe.get("tags", []):
        tag_name = tag if isinstance(tag, str) else tag.get("name", "")
        if tag_name:
            kw = _get_or_create_keyword(tag_name)
            keywords.append({"id": kw["id"], "name": kw["name"]})

    # All ingredients go into the first step
    raw_ings = recipe.get("recipeIngredient", [])
    ingredients = []
    for i, ing in enumerate(raw_ings):
        text = ing if isinstance(ing, str) else (ing.get("note") or ing.get("display") or ing.get("originalText") or "")
        if text:
            ingredients.append({
                "food": {"name": text},
                "unit": None,
                "amount": 0,
                "note": "",
                "order": i,
                "no_amount": True,
                "original_text": text,
            })

    raw_steps = recipe.get("recipeInstructions", [])
    steps = []
    for i, step in enumerate(raw_steps):
        text = step.get("text", "") if isinstance(step, dict) else str(step)
        title = step.get("title", "") if isinstance(step, dict) else ""
        steps.append({
            "name": title,
            "instruction": text,
            "ingredients": ingredients if i == 0 else [],
            "time": 0,
            "order": i,
            "show_as_header": bool(title),
        })

    if not steps:
        steps = [{"name": "", "instruction": "", "ingredients": ingredients,
                  "time": 0, "order": 0, "show_as_header": False}]

    body = {
        "name": name,
        "description": recipe.get("description", ""),
        "keywords": keywords,
        "steps": steps,
        "working_time": _parse_duration(recipe.get("prepTime")),
        "waiting_time": _parse_duration(recipe.get("performTime")),
        "servings": _parse_servings(recipe.get("recipeYield", "4")),
        "servings_text": "servings",
        "source_url": recipe.get("orgURL") or "",
        "internal": True,
        "private": False,
    }

    result = _post("/api/recipe/", body)
    recipe_id = str(result["id"])
    return recipe_id, recipe_id


def add_tags_to_recipe(recipe_id: str, tags: list[str]) -> tuple[str, str]:
    detail = _get(f"/api/recipe/{recipe_id}/")
    existing = {kw["name"].lower() for kw in detail.get("keywords", [])}
    keywords = list(detail.get("keywords", []))
    for tag in tags:
        if tag.lower() not in existing:
            kw = _get_or_create_keyword(tag)
            keywords.append({"id": kw["id"], "name": kw["name"]})
    _patch(f"/api/recipe/{recipe_id}/", {"keywords": keywords})
    return recipe_id, recipe_id


# ── meal plan ─────────────────────────────────────────────────────────────────

def _get_or_create_meal_type(name: str) -> dict:
    data = _get("/api/meal-type/")
    for mt in data.get("results", []):
        if mt["name"].lower() == name.lower():
            return mt
    return _post("/api/meal-type/", {"name": name, "order": 0})


def add_to_mealplan(recipe_id: str, plan_date: str, entry_type: str = "dinner") -> dict:
    meal_type = _get_or_create_meal_type(entry_type.capitalize())
    return _post("/api/meal-plan/", {
        "recipe": {"id": int(recipe_id)},
        "from_date": plan_date,
        "to_date": plan_date,
        "meal_type": {"id": meal_type["id"]},
        "title": "",
        "note": "",
        "servings": 4,
    })


def week_dates(start: date = None, count: int = 7) -> list[str]:
    start = start or date.today()
    return [(start + timedelta(days=i)).isoformat() for i in range(count)]


# ── shopping list ─────────────────────────────────────────────────────────────

def create_shopping_list(name: str) -> str:
    result = _post("/api/shopping-list/", {"name": name[:32], "description": ""})
    return str(result["id"])


def add_shopping_items(list_id: str, items: list[str]) -> None:
    for item in items:
        try:
            _post("/api/shopping-list-entry/", {
                "shopping_lists": [{"id": int(list_id)}],
                "food": {"name": item},
                "unit": None,
                "amount": 0,
                "checked": False,
            })
        except Exception as e:
            print(f"Shopping item error ({item!r}): {e}")


# ── housekeeping ──────────────────────────────────────────────────────────────

def delete_duplicate_recipes() -> list[str]:
    return []  # create_recipe deletes by name before creating — no dupes accumulate


def debug_tandoor() -> dict:
    raw = _get("/api/recipe/", params={"page": 1, "page_size": 5})
    return {"top_level_keys": list(raw.keys()), "sample": raw}
