"""Top-level API router assembly."""

from fastapi import APIRouter

from app.api.routes import auth, example, items, jobs, products, system

api_router = APIRouter()
api_router.include_router(system.router)
api_router.include_router(example.router)
api_router.include_router(auth.router)
api_router.include_router(products.router)
api_router.include_router(jobs.router)
api_router.include_router(items.router)
