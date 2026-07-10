"""Firecrawl-backed source extraction — fallback for non-Shopify brand sites.

Adapts Firecrawl's structured extraction (`PRODUCT_SCHEMA`) onto the Shopify
product shape the enrichment pipeline already consumes (`title`, `body_html`,
`images: [{"src": ...}]`, `variants`). A scraped page carries no per-variant
data, so ``variants`` stays empty — no weight proposals from this path
(assumed trade-off).
"""

from typing import Any

from app.api.schemas import Product
from app.clients.firecrawl import FirecrawlClient


def extract_source_product(
    firecrawl: FirecrawlClient, url: str
) -> dict[str, Any] | None:
    """Extract one product page via Firecrawl, in the Shopify-product shape.

    Returns None when Firecrawl yields no structured result. Raises
    ExternalServiceError on transport/upstream failures (like `scrape`).
    """
    extracted = firecrawl.extract_product(url)
    if extracted is None:
        return None
    images = [str(u) for u in extracted.get("images") or [] if u]
    references = [str(code) for code in extracted.get("reference_codes") or [] if code]
    return {
        "title": extracted.get("title"),
        "body_html": extracted.get("description"),
        "images": [{"src": u} for u in images],
        "variants": [],  # no variant data on a scraped page → no weights
        "tags": None,
        "_firecrawl": True,
        "_reference_codes": references,
    }


def _normalize(value: Any) -> str:
    """Case- and whitespace-insensitive comparison key."""
    return "".join(str(value or "").split()).lower()


def reference_matches(product: Product, extracted: dict[str, Any]) -> bool:
    """True when the product's reference code or a variant barcode shows up
    in the extracted reference codes, title, or description (containment,
    case/whitespace-insensitive)."""
    needles = {_normalize(v.barcode) for v in product.variants if v.barcode}
    needles.add(_normalize(product.reference_code))
    needles.discard("")
    if not needles:
        return False
    haystacks = [_normalize(code) for code in extracted.get("_reference_codes") or []]
    haystacks.append(_normalize(extracted.get("title")))
    haystacks.append(_normalize(extracted.get("body_html")))
    return any(
        needle in haystack for needle in needles for haystack in haystacks if haystack
    )
