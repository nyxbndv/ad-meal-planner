import os
import traceback

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from app.config import settings
from app.routes.planner import router

app = FastAPI(title="Ad Meal Planner")
app.include_router(router)


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    traceback.print_exc()
    return JSONResponse(status_code=500, content={"detail": str(exc)})


os.makedirs(settings.recipe_pages_dir, exist_ok=True)
app.mount("/recipes", StaticFiles(directory=settings.recipe_pages_dir), name="recipe_pages")
app.mount("/", StaticFiles(directory="app/static", html=True), name="static")
