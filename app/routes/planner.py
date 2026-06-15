import mimetypes
from datetime import date

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
from app.services.staples import filter_ingredients
from app.services.vision import extract_sale_items

router = APIRouter()

ALLOWED_TYPES = {"image/jpeg", "image/png", "image/webp", "image/gif"}


@router.post("/api/plan")
async def create_meal_plan(images: list[UploadFile] = File(...), store: str = Form("")):
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

    # 2. Fetch and score existing Tandoor recipes
    summaries = fetch_all_recipes()
    detailed = []
    for summary in summaries:
        try:
            detailed.append(fetch_recipe_detail(summary["id"]))
        except Exception:
            detailed.append(summary)

    target = settings.recipes_per_week
    matched = rank_existing_recipes(detailed, sale_items, top_n=target // 2 + 1)

    # 3. Generate new recipes to fill remaining slots
    new_count = max(1, target - len(matched))
    existing_names = [r.get("name", "") for r in matched]
    tags = ["claude-generated", "meal-planner"]
    if store:
        tags.append(store.lower().replace(" ", "-"))
    generated = generate_recipes(sale_items, existing_names, count=new_count, tags=tags)

    # 4. Create new recipes in Tandoor
    matched_tag = ["meal-planner"] + ([store.lower().replace(" ", "-")] if store else [])
    created = []
    for recipe in generated:
        try:
            recipe_id, _ = create_recipe(recipe)
            created.append({"name": recipe["name"], "id": recipe_id})
        except Exception as e:
            created.append({"name": recipe["name"], "id": None, "error": str(e)})

    matched_for_plan = []
    for recipe in matched:
        try:
            new_id, _ = add_tags_to_recipe(str(recipe["id"]), matched_tag)
            matched_for_plan.append({"name": recipe.get("name"), "id": new_id})
        except Exception as e:
            print(f"Tag error for {recipe.get('name')}: {e}")
            matched_for_plan.append({"name": recipe.get("name"), "id": str(recipe.get("id"))})

    # 5. Add all recipes to the meal plan across the week
    dates = week_dates(start=date.today(), count=target)
    plan_entries = []

    all_recipes_for_plan = (
        matched_for_plan
        + [{"name": c["name"], "id": c.get("id")} for c in created]
    )

    for i, entry in enumerate(all_recipes_for_plan[:target]):
        if not entry["id"]:
            continue
        try:
            add_to_mealplan(entry["id"], dates[i])
            plan_entries.append({"date": dates[i], "recipe": entry["name"]})
        except Exception as e:
            print(f"Meal plan error for {entry['name']}: {e}")

    # 6. Build and push shopping list
    all_ingredients = []
    for recipe in matched:
        all_ingredients.extend(filter_ingredients(recipe.get("recipeIngredient", [])))
    for recipe in generated:
        all_ingredients.extend(filter_ingredients(recipe.get("recipeIngredient", [])))

    deduped = list(dict.fromkeys(all_ingredients))

    list_name = f"Week of {date.today().strftime('%b %-d, %Y')}"
    shopping_list_id = None
    try:
        shopping_list_id = create_shopping_list(list_name)
        if deduped:
            add_shopping_items(shopping_list_id, deduped)
        else:
            print("Shopping list: no ingredients after filtering staples")
    except Exception as e:
        print(f"Shopping list error: {e}")

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


@router.get("/api/debug")
def debug():
    return debug_tandoor()


@router.get("/api/health")
def health():
    return {"status": "ok"}
