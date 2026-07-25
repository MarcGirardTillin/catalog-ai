"""Schemas for catalog classification (product-search filter options)."""

from pydantic import BaseModel


class FilterOption(BaseModel):
    """One selectable value in a search filter (brand, category, …)."""

    id: int
    title: str
    parent_id: int | None = None
    # Catégories uniquement : poids par défaut (kg) appliqué quand aucun
    # poids source (0 = non renseigné). Champ Xano `default_weight_kg`.
    default_weight_kg: float | None = None


class CategoryWeightRequest(BaseModel):
    """Poids par défaut (kg) d'une catégorie ; 0 = effacer."""

    default_weight_kg: float


class CatalogFilters(BaseModel):
    """Classification lists backing the product-search filters."""

    brands: list[FilterOption] = []
    categories: list[FilterOption] = []
    compositions: list[FilterOption] = []
    seasons: list[FilterOption] = []
    suppliers: list[FilterOption] = []
    tags: list[FilterOption] = []
