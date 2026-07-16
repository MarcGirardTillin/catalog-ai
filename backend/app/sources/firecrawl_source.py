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

# Extracted technical text fields carried on the Shopify-shaped dict under
# underscore keys (they have no Shopify equivalent). The copywriter context
# picks them up; anything absent from the page simply stays out.
_TEXT_FIELD_KEYS = {
    "features": "_features",
    "composition": "_composition",
    "manufacturing_country": "_manufacturing_country",
    "care": "_care",
}


def _apply_text_fields(target: dict[str, Any], extracted: dict[str, Any]) -> None:
    """Copy the extracted technical text fields onto `target` (in place)."""
    for src_key, dst_key in _TEXT_FIELD_KEYS.items():
        value = extracted.get(src_key)
        if value:
            target[dst_key] = value


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
    result: dict[str, Any] = {
        "title": extracted.get("title"),
        "body_html": extracted.get("description"),
        "images": [{"src": u} for u in images],
        "variants": [],  # no variant data on a scraped page → no weights
        "tags": None,
        "_firecrawl": True,
        "_reference_codes": references,
    }
    _apply_text_fields(result, extracted)
    return result


def merge_extracted_text(
    source_product: dict[str, Any], extracted: dict[str, Any]
) -> dict[str, Any]:
    """Hybrid mode: graft the page's rich text onto a Shopify JSON product.

    The Shopify storefront JSON often carries a one-sentence `body_html`
    (vérifié live : Moschino → 100 caractères) while the rendered page holds
    the real details behind accordions. The Shopify product stays the
    authority for matching/variants/images; only the TEXT is enriched here:
    the page description lands under `_page_description` (never overwrites
    `body_html`) and the technical fields under their underscore keys.
    """
    merged = dict(source_product)
    description = extracted.get("description")
    if description:
        merged["_page_description"] = description
    _apply_text_fields(merged, extracted)
    return merged


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
