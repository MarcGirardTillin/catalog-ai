"""Catalog metadata routes — classification options for search filters."""

from fastapi import APIRouter, Depends

from app.api.deps import XanoDep, get_current_user
from app.api.exceptions import AppException
from app.api.schemas.catalog import CatalogFilters, CategoryWeightRequest, FilterOption

router = APIRouter(
    prefix="/catalog",
    tags=["catalog"],
    dependencies=[Depends(get_current_user)],
)


@router.get("/filters", response_model=CatalogFilters)
def get_filters(xano: XanoDep) -> CatalogFilters:
    """Brands, categories, seasons, suppliers and tags for the search filters."""
    return CatalogFilters.model_validate(xano.get_classification())


@router.put("/categories/{category_id}/default-weight", response_model=FilterOption)
def set_category_default_weight(
    category_id: int, payload: CategoryWeightRequest, xano: XanoDep
) -> FilterOption:
    """Poids par défaut (kg) d'une catégorie, éditable depuis CatalogAI.

    Le champ vit dans la table catégorie Xano (« comme la marque », décision
    Marc) — appliqué quand aucun poids source à l'apply d'enrichissement et
    au transfert d'import. Le titre actuel est relu et RENVOYÉ avec le poids
    (l'endpoint Xano remplace les champs absents — vérifié live).
    """
    categories = xano.get_classification().get("categories", [])
    current = next((c for c in categories if int(c["id"]) == category_id), None)
    if current is None:
        raise AppException(
            status_code=404, code="not_found", message="Category not found"
        )
    xano.set_category_default_weight(
        category_id, payload.default_weight_kg, title=str(current["title"])
    )
    return FilterOption(
        id=category_id,
        title=str(current["title"]),
        parent_id=current.get("parent_id"),
        default_weight_kg=payload.default_weight_kg,
    )
