import mimetypes

from fastapi import APIRouter, File, HTTPException, UploadFile
from fastapi.responses import Response

from app.config import settings
from app.services.exporter import build_export_zip
from app.services.generator import generate_recipes
from app.services.matcher import rank_existing_recipes
from app.services.mealie import fetch_all_recipes, fetch_recipe_detail
from app.services.vision import extract_sale_items

router = APIRouter()

ALLOWED_TYPES = {"image/jpeg", "image/png", "image/webp", "image/gif"}


@router.post("/api/plan")
async def create_meal_plan(images: list[UploadFile] = File(...)):
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

    mealie_summaries = fetch_all_recipes()
    detailed = []
    for summary in mealie_summaries:
        try:
            detailed.append(fetch_recipe_detail(summary["slug"]))
        except Exception:
            detailed.append(summary)

    existing_week = settings.recipes_per_week
    matched = rank_existing_recipes(detailed, sale_items, top_n=existing_week // 2 + 1)

    new_count = max(1, existing_week - len(matched))
    existing_names = [r.get("name", "") for r in matched]
    generated = generate_recipes(sale_items, existing_names, count=new_count)

    zip_bytes = build_export_zip(generated, matched, sale_items)

    return Response(
        content=zip_bytes,
        media_type="application/zip",
        headers={"Content-Disposition": "attachment; filename=meal_plan.zip"},
    )


@router.get("/api/health")
def health():
    return {"status": "ok"}
