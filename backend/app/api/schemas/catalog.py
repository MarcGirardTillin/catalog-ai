"""Schemas for catalog classification (product-search filter options)."""

from pydantic import BaseModel


class FilterOption(BaseModel):
    """One selectable value in a search filter (brand, category, …)."""

    id: int
    title: str
    parent_id: int | None = None


class CatalogFilters(BaseModel):
    """Classification lists backing the product-search filters."""

    brands: list[FilterOption] = []
    categories: list[FilterOption] = []
    seasons: list[FilterOption] = []
    suppliers: list[FilterOption] = []
    tags: list[FilterOption] = []
