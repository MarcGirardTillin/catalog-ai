"""Top-level API router assembly."""

from fastapi import APIRouter

from app.api.routes import (
    auth,
    brands,
    catalog,
    example,
    imaging,
    import_profiles,
    imports,
    instructions,
    items,
    jobs,
    locations,
    products,
    settings,
    stats,
    system,
    usage,
)

api_router = APIRouter()
api_router.include_router(system.router)
api_router.include_router(example.router)
api_router.include_router(auth.router)
api_router.include_router(products.router)
api_router.include_router(imaging.router)
api_router.include_router(brands.router)
api_router.include_router(catalog.router)
api_router.include_router(jobs.router)
api_router.include_router(imports.router)
api_router.include_router(import_profiles.router)
api_router.include_router(locations.router)
api_router.include_router(items.router)
api_router.include_router(stats.router)
api_router.include_router(settings.router)
api_router.include_router(instructions.router)
api_router.include_router(usage.router)
