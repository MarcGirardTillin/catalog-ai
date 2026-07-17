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


_COLOR_OPTION_NAMES = {"color", "colour", "couleur"}


def candidate_color(candidate: dict[str, Any]) -> str | None:
    """The candidate's color(s) from its Shopify options, when declared.

    Certains sites (une fiche par coloris, ex. Lemaire) n'ont pas d'option
    couleur du tout : None — l'UI affiche alors le slug de l'URL en repli.
    """
    options = candidate.get("options")
    if not isinstance(options, list):
        return None
    position: int | None = None
    for option in options:
        if not isinstance(option, dict):
            continue
        if str(option.get("name") or "").strip().lower() in _COLOR_OPTION_NAMES:
            raw = option.get("position")
            position = int(raw) if isinstance(raw, int) else None
            break
    if position is None:
        return None
    key = f"option{position}"
    values: list[str] = []
    for variant in candidate.get("variants") or []:
        value = str(variant.get(key) or "").strip()
        if value and value not in values:
            values.append(value)
    return ", ".join(values[:3]) or None


def _title_similarity(a: str, b: str) -> float:
    return SequenceMatcher(None, a.lower(), b.lower()).ratio()


def reference_key(value: Any) -> str:
    """Formatting-insensitive comparison key for reference codes.

    Chaque système écrit la même référence à sa façon (vécu Lemaire :
    Tillin « BG0223 LL0108 » vs SKU site « BG0223 LL0108_GR211_OS », parfois
    des tirets) : on ne garde que les alphanumériques, en minuscules.
    """
    return "".join(ch for ch in str(value or "").lower() if ch.isalnum())


def score_product_match(product: Product, candidate: dict[str, Any]) -> float:
    """Score one full candidate product JSON against a Tillin product."""
    if _barcodes(product) & _candidate_barcodes(candidate):
        return SCORE_BARCODE

    reference = reference_key(product.reference_code)
    if reference:
        skus = _candidate_skus(candidate)
        sku_keys = {reference_key(sku) for sku in skus}
        if reference in sku_keys:
            return SCORE_REFERENCE_EXACT
        haystacks = (
            reference_key(candidate.get("handle")),
            reference_key(candidate.get("title")),
            reference_key(candidate.get("tags")),
            *sku_keys,
        )
        if any(reference in h for h in haystacks if h):
            return SCORE_REFERENCE_CONTAINS

    # The color tie-break between same-reference colorways happens in the
    # resolver (it needs the FULL candidate list, not one pairwise score).
    if product.title:
        return TITLE_SIMILARITY_WEIGHT * _title_similarity(
            product.title, str(candidate.get("title") or "")
        )
    return 0.0
