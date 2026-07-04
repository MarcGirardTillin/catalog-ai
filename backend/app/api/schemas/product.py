"""Canonical product schema (destination-agnostic).

This is the internal contract the engine reads and writes, **not** the Tillin
(Xano) schema. The `xano` client maps raw Tillin payloads onto these models;
future `destinations/` adapters translate them onto their own targets. Keep this
free of any Tillin-specific field name.
"""

from pydantic import BaseModel, Field


class ProductVariant(BaseModel):
    """A single sellable variant (style x color x size) of a product."""

    id: int | None = None
    sku: str | None = None
    barcode: str | None = None
    weight: float | None = None
    weight_unit: str | None = None


class ProductImage(BaseModel):
    """An image associated with a product."""

    url: str
    position: int | None = None


class Brand(BaseModel):
    """The brand a product belongs to, with its source website(s)."""

    id: int | None = None
    name: str | None = None
    # A brand may sell across several stores/domains; the resolver searches all.
    website_urls: list[str] = Field(default_factory=list)


class Product(BaseModel):
    """Canonical product as consumed by the enrichment/intake engine."""

    id: int
    title: str | None = None
    reference_code: str | None = None
    brand: Brand | None = None
    season: str | None = None
    category: str | None = None
    department: str | None = None
    variants: list[ProductVariant] = Field(default_factory=list)
    images: list[ProductImage] = Field(default_factory=list)
