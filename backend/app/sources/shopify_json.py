"""Shopify storefront JSON access + candidate scoring.

Scoring priority (plan; replaces the old Xano `1079` SKU-first scorer):
1. variant barcode / EAN exact — most reliable cross-catalog key
2. Tillin `product_reference_code` vs the site's variant SKUs / handle /
   title / tags (exact, then contains)
3. title fuzzy similarity — tie-breaker only
The Tillin-generated SKU is deliberately NOT used: it never matches the
brand's own SKUs.
"""

from difflib import SequenceMatcher
from typing import Any

import httpx

from app.api.schemas import Product

SCORE_BARCODE = 1.0
SCORE_REFERENCE_EXACT = 0.9
SCORE_REFERENCE_CONTAINS = 0.75
TITLE_SIMILARITY_WEIGHT = 0.6  # fuzzy title alone can never auto-stage


def search_suggest(
    client: httpx.Client, site: str, query: str, *, limit: int = 8
) -> list[dict[str, Any]]:
    """Query Shopify's predictive search; returns candidate product stubs."""
    response = client.get(
        f"{site.rstrip('/')}/search/suggest.json",
        params={
            "q": query,
            "resources[type]": "product",
            "resources[limit]": str(limit),
            "resources[options][unavailable_products]": "last",
        },
    )
    response.raise_for_status()
    payload = response.json()
    products = payload.get("resources", {}).get("results", {}).get("products", [])
    return products if isinstance(products, list) else []


def fetch_product(
    client: httpx.Client, site: str, handle: str
) -> dict[str, Any] | None:
    """Fetch the full product JSON for a handle; None when not found."""
    response = client.get(f"{site.rstrip('/')}/products/{handle}.json")
    if response.status_code == 404:
        return None
    response.raise_for_status()
    product = response.json().get("product")
    return product if isinstance(product, dict) else None


def _barcodes(product: Product) -> set[str]:
    return {v.barcode.strip() for v in product.variants if v.barcode}


def _candidate_barcodes(candidate: dict[str, Any]) -> set[str]:
    return {
        str(v.get("barcode")).strip()
        for v in candidate.get("variants", [])
        if v.get("barcode")
    }


def _candidate_skus(candidate: dict[str, Any]) -> set[str]:
    return {
        str(v.get("sku")).strip().lower()
        for v in candidate.get("variants", [])
        if v.get("sku")
    }


def _title_similarity(a: str, b: str) -> float:
    return SequenceMatcher(None, a.lower(), b.lower()).ratio()


def score_product_match(product: Product, candidate: dict[str, Any]) -> float:
    """Score one full candidate product JSON against a Tillin product."""
    if _barcodes(product) & _candidate_barcodes(candidate):
        return SCORE_BARCODE

    reference = (product.reference_code or "").strip().lower()
    if reference:
        skus = _candidate_skus(candidate)
        handle = str(candidate.get("handle") or "").lower()
        title = str(candidate.get("title") or "").lower()
        tags = str(candidate.get("tags") or "").lower()
        if reference in skus:
            return SCORE_REFERENCE_EXACT
        haystacks = (handle, title, tags, *skus)
        if any(reference in h for h in haystacks if h):
            return SCORE_REFERENCE_CONTAINS

    # TODO(plan): add the product's color as a tie-breaker once the canonical
    # schema carries variant color options.
    if product.title:
        return TITLE_SIMILARITY_WEIGHT * _title_similarity(
            product.title, str(candidate.get("title") or "")
        )
    return 0.0
