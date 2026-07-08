"""Top-level API router assembly."""

from fastapi import APIRouter

from app.api.routes import (
    auth,
    catalog,
    example,
    instructions,
    items,
    jobs,
    products,
    settings,
    stats,
    system,
)

api_router = APIRouter()
api_router.include_router(system.router)
api_router.include_router(example.router)
api_router.include_router(auth.router)
api_router.include_router(products.router)
api_router.include_router(catalog.router)
api_router.include_router(jobs.router)
api_router.include_router(items.router)
api_router.include_router(stats.router)
api_router.include_router(settings.router)
api_router.include_router(instructions.router)
