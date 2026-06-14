from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from app.routes.planner import router

app = FastAPI(title="Ad Meal Planner")
app.include_router(router)
app.mount("/", StaticFiles(directory="app/static", html=True), name="static")
