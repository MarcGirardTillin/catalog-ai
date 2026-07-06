"""Catalog metadata routes — classification options for search filters."""

from fastapi import APIRouter, Depends

from app.api.deps import XanoDep, get_current_user
from app.api.schemas.catalog import CatalogFilters

router = APIRouter(
    prefix="/catalog",
    tags=["catalog"],
    dependencies=[Depends(get_current_user)],
)


@router.get("/filters", response_model=CatalogFilters)
def get_filters(xano: XanoDep) -> CatalogFilters:
    """Brands, categories, seasons, suppliers and tags for the search filters."""
    return CatalogFilters.model_validate(xano.get_classification())
