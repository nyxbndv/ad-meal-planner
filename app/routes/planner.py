import mimetypes
from datetime import date, timedelta

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from fastapi.responses import JSONResponse

from app.config import settings
from app.services.generator import generate_recipes
from app.services.matcher import rank_existing_recipes
from app.services.tandoor import (
    add_shopping_items,
    add_to_mealplan,
    add_tags_to_recipe,
    create_recipe,
    create_shopping_list,
    debug_tandoor,
    delete_duplicate_recipes,
    fetch_all_recipes,
    fetch_recipe_detail,
    week_dates,
)
from app.services.html_export import write_recipe_page
from app.services.mealie import (
    add_shopping_items as mealie_add_shopping_items,
    add_tags_to_recipe as mealie_add_tags_to_recipe,
    add_to_mealplan as mealie_add_to_mealplan,
    create_recipe_from_url,
    create_shopping_list as mealie_create_shopping_list,
    debug_mealie,
    fetch_all_recipes as mealie_fetch_all_recipes,
    fetch_recipe_detail as mealie_fetch_recipe_detail,
    week_dates as mealie_week_dates,
)
from app.services.staples import filter_ingredients
from app.services.vision import extract_sale_items

router = APIRouter()

ALLOWED_TYPES = {"image/jpeg", "image/png", "image/webp", "image/gif"}


@router.post("/api/plan")
async def create_meal_plan(images: list[UploadFile] = File(...), store: str = Form(""), custom_instructions: str = Form("")):
    if not images:
        raise HTTPException(status_code=400, detail="At least one image is required.")

    image_data = []
    for img in images:
        media_type = img.content_type or mimetypes.guess_type(img.filename)[0] or "image/jpeg"
        if media_type not in ALLOWED_TYPES:
            raise HTTPException(status_code=400, detail=f"Unsupported file type: {media_type}")
        image_data.append((await img.read(), media_type))

    # 1. Extract sale items from ad photos
    sale_items = extract_sale_items(image_data)
    if not sale_items:
        raise HTTPException(status_code=422, detail="No sale items could be extracted from images.")
    print(f"[1/6] Found {len(sale_items)} sale items: {[i['name'] for i in sale_items]}")

    # 2. Fetch and score existing Tandoor recipes
    summaries = fetch_all_recipes()
    print(f"[2/6] Fetched {len(summaries)} recipes from Tandoor")
    detailed = []
    for summary in summaries:
        try:
            detailed.append(fetch_recipe_detail(summary["id"]))
        except Exception:
            detailed.append(summary)

    target = settings.recipes_per_week
    matched = rank_existing_recipes(detailed, sale_items, top_n=target // 2 + 1)
    print(f"[2/6] Matched {len(matched)} existing recipes: {[r.get('name') for r in matched]}")

    # 3. Generate new recipes to fill remaining slots
    new_count = max(1, target - len(matched))
    existing_names = [r.get("name", "") for r in matched]
    tags = ["claude-generated", "meal-planner"]
    if store:
        tags.append(store.lower().replace(" ", "-"))
    print(f"[3/6] Generating {new_count} new recipes...")
    generated = generate_recipes(sale_items, existing_names, count=new_count, tags=tags, custom_instructions=custom_instructions)
    print(f"[3/6] Generated: {[r.get('name') for r in generated]}")

    # 4. Create new recipes in Tandoor
    matched_tag = ["meal-planner"] + ([store.lower().replace(" ", "-")] if store else [])
    created = []
    for recipe in generated:
        try:
            recipe_id, _ = create_recipe(recipe)
            created.append({"name": recipe["name"], "id": recipe_id})
            print(f"[4/6] Created recipe: {recipe['name']} (id={recipe_id})")
        except Exception as e:
            created.append({"name": recipe["name"], "id": None, "error": str(e)})
            print(f"[4/6] Failed to create recipe {recipe['name']}: {e}")

    matched_for_plan = []
    for recipe in matched:
        try:
            new_id, _ = add_tags_to_recipe(str(recipe["id"]), matched_tag)
            matched_for_plan.append({"name": recipe.get("name"), "id": new_id})
            print(f"[4/6] Tagged existing recipe: {recipe.get('name')}")
        except Exception as e:
            print(f"[4/6] Tag error for {recipe.get('name')}: {e}")
            matched_for_plan.append({"name": recipe.get("name"), "id": str(recipe.get("id"))})

    # 5. Add all recipes to the meal plan — dinner each night, leftovers for lunch next day
    dates = week_dates(start=date.today(), count=target)
    plan_entries = []

    all_recipes_for_plan = (
        matched_for_plan
        + [{"name": c["name"], "id": c.get("id")} for c in created]
    )

    print(f"[5/6] Adding {len(all_recipes_for_plan)} recipes to meal plan (dinner + next-day lunch)...")
    for i, entry in enumerate(all_recipes_for_plan[:target]):
        if not entry["id"]:
            print(f"[5/6] Skipping {entry['name']} — no id")
            continue
        dinner_date = dates[i]
        lunch_date = (date.fromisoformat(dinner_date) + timedelta(days=1)).isoformat()
        try:
            add_to_mealplan(entry["id"], dinner_date, entry_type="dinner", recipe_name=entry["name"])
            plan_entries.append({"date": dinner_date, "meal": "dinner", "recipe": entry["name"]})
            print(f"[5/6] Dinner {dinner_date}: {entry['name']}")
        except Exception as e:
            print(f"[5/6] Dinner plan error for {entry['name']}: {e}")
        try:
            add_to_mealplan(entry["id"], lunch_date, entry_type="lunch", recipe_name=entry["name"])
            plan_entries.append({"date": lunch_date, "meal": "lunch", "recipe": f"{entry['name']} (leftovers)"})
            print(f"[5/6] Lunch  {lunch_date}: {entry['name']} (leftovers)")
        except Exception as e:
            print(f"[5/6] Lunch plan error for {entry['name']}: {e}")

    # 6. Build and push shopping list
    all_ingredients = []
    for recipe in matched:
        all_ingredients.extend(filter_ingredients(recipe.get("recipeIngredient", [])))
    for recipe in generated:
        all_ingredients.extend(filter_ingredients(recipe.get("recipeIngredient", [])))

    deduped = list(dict.fromkeys(all_ingredients))
    print(f"[6/6] Shopping list: {len(deduped)} items")

    list_name = f"Week of {date.today().strftime('%b %-d, %Y')}"
    shopping_list_id = None
    try:
        shopping_list_id = create_shopping_list(list_name)
        if deduped:
            add_shopping_items(shopping_list_id, deduped)
        else:
            print("[6/6] No ingredients after filtering staples")
    except Exception as e:
        print(f"[6/6] Shopping list error: {e}")

    tandoor_base = settings.tandoor_url.rstrip("/")

    return JSONResponse({
        "sale_items_found": len(sale_items),
        "meal_plan": plan_entries,
        "new_recipes": [
            {
                "name": c["name"],
                "url": f"{tandoor_base}/recipe/{c['id']}/" if c.get("id") else None,
            }
            for c in created
        ],
        "existing_recipes_matched": [
            {
                "name": r.get("name"),
                "matched_sales": r.get("_matched_sales", []),
                "url": f"{tandoor_base}/recipe/{r.get('id')}/",
            }
            for r in matched
        ],
        "shopping_list": {
            "name": list_name,
            "items": len(deduped),
            "url": f"{tandoor_base}/shopping-list/" if shopping_list_id else None,
        },
    })


@router.post("/api/plan-mealie")
async def create_meal_plan_mealie(images: list[UploadFile] = File(...), store: str = Form(""), custom_instructions: str = Form("")):
    """Same pipeline as /api/plan, but pushes recipes to Mealie by rendering them as
    static HTML (schema.org/Recipe JSON-LD) and having Mealie scrape the URL,
    instead of calling Mealie's recipe CRUD API directly."""
    if not images:
        raise HTTPException(status_code=400, detail="At least one image is required.")

    image_data = []
    for img in images:
        media_type = img.content_type or mimetypes.guess_type(img.filename)[0] or "image/jpeg"
        if media_type not in ALLOWED_TYPES:
            raise HTTPException(status_code=400, detail=f"Unsupported file type: {media_type}")
        image_data.append((await img.read(), media_type))

    sale_items = extract_sale_items(image_data)
    if not sale_items:
        raise HTTPException(status_code=422, detail="No sale items could be extracted from images.")
    print(f"[1/6] Found {len(sale_items)} sale items: {[i['name'] for i in sale_items]}")

    summaries = mealie_fetch_all_recipes()
    print(f"[2/6] Fetched {len(summaries)} recipes from Mealie")
    detailed = []
    for summary in summaries:
        try:
            detailed.append(mealie_fetch_recipe_detail(summary["slug"]))
        except Exception:
            detailed.append(summary)

    target = settings.recipes_per_week
    matched = rank_existing_recipes(detailed, sale_items, top_n=target // 2 + 1)
    print(f"[2/6] Matched {len(matched)} existing recipes: {[r.get('name') for r in matched]}")

    new_count = max(1, target - len(matched))
    existing_names = [r.get("name", "") for r in matched]
    tags = ["claude-generated", "meal-planner"]
    if store:
        tags.append(store.lower().replace(" ", "-"))
    print(f"[3/6] Generating {new_count} new recipes...")
    generated = generate_recipes(sale_items, existing_names, count=new_count, tags=tags, custom_instructions=custom_instructions)
    print(f"[3/6] Generated: {[r.get('name') for r in generated]}")

    matched_tag = ["meal-planner"] + ([store.lower().replace(" ", "-")] if store else [])
    created = []
    for recipe in generated:
        try:
            _, page_url = write_recipe_page(recipe)
            slug, recipe_id = create_recipe_from_url(page_url)
            created.append({"name": recipe["name"], "id": recipe_id, "slug": slug})
            print(f"[4/6] Imported recipe via URL: {recipe['name']} (slug={slug})")
        except Exception as e:
            created.append({"name": recipe["name"], "id": None, "error": str(e)})
            print(f"[4/6] Failed to import recipe {recipe['name']}: {e}")

    matched_for_plan = []
    for recipe in matched:
        try:
            new_slug, new_id = mealie_add_tags_to_recipe(recipe["slug"], matched_tag)
            matched_for_plan.append({"name": recipe.get("name"), "id": new_id, "slug": new_slug})
            print(f"[4/6] Tagged existing recipe: {recipe.get('name')}")
        except Exception as e:
            print(f"[4/6] Tag error for {recipe.get('name')}: {e}")
            matched_for_plan.append({"name": recipe.get("name"), "id": recipe.get("id"), "slug": recipe.get("slug")})

    dates = mealie_week_dates(start=date.today(), count=target)
    plan_entries = []

    all_recipes_for_plan = (
        matched_for_plan
        + [{"name": c["name"], "id": c.get("id"), "slug": c.get("slug")} for c in created]
    )

    print(f"[5/6] Adding {len(all_recipes_for_plan)} recipes to meal plan (dinner + next-day lunch)...")
    for i, entry in enumerate(all_recipes_for_plan[:target]):
        if not entry["id"]:
            print(f"[5/6] Skipping {entry['name']} — no id")
            continue
        dinner_date = dates[i]
        lunch_date = (date.fromisoformat(dinner_date) + timedelta(days=1)).isoformat()
        try:
            mealie_add_to_mealplan(entry["id"], dinner_date, entry_type="dinner")
            plan_entries.append({"date": dinner_date, "meal": "dinner", "recipe": entry["name"]})
            print(f"[5/6] Dinner {dinner_date}: {entry['name']}")
        except Exception as e:
            print(f"[5/6] Dinner plan error for {entry['name']}: {e}")
        try:
            mealie_add_to_mealplan(entry["id"], lunch_date, entry_type="lunch")
            plan_entries.append({"date": lunch_date, "meal": "lunch", "recipe": f"{entry['name']} (leftovers)"})
            print(f"[5/6] Lunch  {lunch_date}: {entry['name']} (leftovers)")
        except Exception as e:
            print(f"[5/6] Lunch plan error for {entry['name']}: {e}")

    all_ingredients = []
    for recipe in matched:
        all_ingredients.extend(filter_ingredients(recipe.get("recipeIngredient", [])))
    for recipe in generated:
        all_ingredients.extend(filter_ingredients(recipe.get("recipeIngredient", [])))

    deduped = list(dict.fromkeys(all_ingredients))
    print(f"[6/6] Shopping list: {len(deduped)} items")

    list_name = f"Week of {date.today().strftime('%b %-d, %Y')}"
    shopping_list_id = None
    try:
        shopping_list_id = mealie_create_shopping_list(list_name)
        if deduped:
            mealie_add_shopping_items(shopping_list_id, deduped)
        else:
            print("[6/6] No ingredients after filtering staples")
    except Exception as e:
        print(f"[6/6] Shopping list error: {e}")

    mealie_base = settings.mealie_url.rstrip("/")

    return JSONResponse({
        "sale_items_found": len(sale_items),
        "meal_plan": plan_entries,
        "new_recipes": [
            {
                "name": c["name"],
                "url": f"{mealie_base}/recipe/{c['slug']}/" if c.get("slug") else None,
            }
            for c in created
        ],
        "existing_recipes_matched": [
            {
                "name": r.get("name"),
                "matched_sales": r.get("_matched_sales", []),
                "url": f"{mealie_base}/recipe/{r.get('slug')}/",
            }
            for r in matched
        ],
        "shopping_list": {
            "name": list_name,
            "items": len(deduped),
            "url": f"{mealie_base}/shopping-lists/{shopping_list_id}" if shopping_list_id else None,
        },
    })


@router.get("/api/debug")
def debug():
    return debug_tandoor()


@router.get("/api/debug-mealie")
def debug_mealie_endpoint():
    return debug_mealie()


@router.get("/api/health")
def health():
    return {"status": "ok"}
