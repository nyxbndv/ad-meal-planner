import httpx

from app.config import settings

BASE = settings.mealie_url.rstrip("/")
HEADERS = {"Authorization": f"Bearer {settings.mealie_api_key}"}


def _get(path: str, params: dict = None) -> dict:
    r = httpx.get(f"{BASE}{path}", headers=HEADERS, params=params, timeout=15)
    r.raise_for_status()
    return r.json()


def fetch_all_recipes() -> list[dict]:
    """Return a flat list of recipe summaries from Mealie."""
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
