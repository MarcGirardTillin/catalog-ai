"""Tests for the shopify_json matcher and the source resolver."""

from typing import Any

import httpx

from app.api.schemas import Brand, Product, ProductVariant
from app.sources.resolver import resolve_source_url
from app.sources.shopify_json import score_product_match

SITE = "https://gramicci.example"

PRODUCT = Product(
    id=1,
    title="Gramicci G-Short Double Navy",
    reference_code="G5FU-T081",
    brand=Brand(id=7, name="Gramicci", website_urls=[SITE]),
    variants=[
        ProductVariant(id=11, sku="TIL-001", barcode="4550479812345"),
        ProductVariant(id=12, sku="TIL-002", barcode="4550479812352"),
    ],
)


def _store(catalog: dict[str, dict[str, Any]]) -> httpx.MockTransport:
    """Fake Shopify store: suggest.json searches the catalog, product JSON by handle."""

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path == "/search/suggest.json":
            query = request.url.params["q"].lower()
            hits = [
                {"handle": handle, "title": product["title"]}
                for handle, product in catalog.items()
                if query in product["title"].lower()
                or any(
                    query == str(v.get("barcode", "")).lower()
                    or query in str(v.get("sku", "")).lower()
                    for v in product["variants"]
                )
                or query in handle
            ]
            return httpx.Response(
                200, json={"resources": {"results": {"products": hits}}}
            )
        if path.startswith("/products/") and path.endswith(".json"):
            handle = path.removeprefix("/products/").removesuffix(".json")
            if handle in catalog:
                return httpx.Response(200, json={"product": catalog[handle]})
            return httpx.Response(404)
        return httpx.Response(404)

    return httpx.MockTransport(handler)


GOOD_CANDIDATE = {
    "title": "G-Short Double Navy",
    "handle": "g-short-double-navy",
    "tags": "shorts, ss25",
    "variants": [
        {"sku": "G5FU-T081-M", "barcode": "4550479812345", "grams": 320},
        {"sku": "G5FU-T081-L", "barcode": "4550479812352", "grams": 340},
    ],
}

DECOY = {
    "title": "Ridge Pant Olive",
    "handle": "ridge-pant-olive",
    "tags": "pants",
    "variants": [{"sku": "G3SU-P001-M", "barcode": "9990000000000"}],
}


def test_barcode_match_scores_highest() -> None:
    assert score_product_match(PRODUCT, GOOD_CANDIDATE) == 1.0


def test_reference_match_without_barcode() -> None:
    candidate = {
        "title": "G-Short",
        "handle": "g-short",
        "tags": "",
        "variants": [{"sku": "G5FU-T081", "barcode": "1112223334445"}],
    }
    product = PRODUCT.model_copy(
        update={"variants": [ProductVariant(id=11, sku="TIL-001")]}
    )
    assert score_product_match(product, candidate) == 0.9


def test_tillin_sku_is_never_used() -> None:
    candidate = {
        "title": "Unrelated Jacket",
        "handle": "unrelated-jacket",
        "tags": "",
        # The site's SKU happens to equal the Tillin SKU — must NOT match.
        "variants": [{"sku": "TIL-001"}],
    }
    product = Product(
        id=2,
        title="Zzz",
        reference_code="REF-XYZ",
        variants=[ProductVariant(id=1, sku="TIL-001")],
    )
    assert score_product_match(product, candidate) < 0.5


def test_resolver_finds_product_by_barcode() -> None:
    transport = _store(
        {"g-short-double-navy": GOOD_CANDIDATE, "ridge-pant-olive": DECOY}
    )
    with httpx.Client(transport=transport) as client:
        result = resolve_source_url(client, PRODUCT, [SITE])

    assert result.status == "resolved"
    assert result.url == f"{SITE}/products/g-short-double-navy"
    assert result.score == 1.0
    assert result.method_used == "shopify_json"


def test_resolver_needs_manual_when_low_confidence() -> None:
    transport = _store({"ridge-pant-olive": DECOY})
    product = PRODUCT.model_copy(
        update={
            "title": "Ridge",  # weak title overlap only
            "reference_code": "NOPE-999",
            "variants": [ProductVariant(id=1, barcode="0000000000000")],
        }
    )
    with httpx.Client(transport=transport) as client:
        result = resolve_source_url(client, product, [SITE])

    assert result.status == "needs_manual"


def test_resolver_skips_without_urls_and_unimplemented_methods() -> None:
    with httpx.Client(transport=_store({})) as client:
        no_urls = resolve_source_url(client, PRODUCT, [])
        firecrawl = resolve_source_url(client, PRODUCT, [SITE], method="firecrawl")

    assert no_urls.status == "skipped"
    assert "website" in (no_urls.reason or "")
    assert firecrawl.status == "skipped"


def test_resolver_aggregates_across_sites() -> None:
    empty_site = "https://empty.example"
    real_store = _store({"g-short-double-navy": GOOD_CANDIDATE})

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "empty.example":
            if request.url.path == "/search/suggest.json":
                return httpx.Response(
                    200, json={"resources": {"results": {"products": []}}}
                )
            return httpx.Response(404)
        return real_store.handle_request(request)

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        result = resolve_source_url(client, PRODUCT, [empty_site, SITE])

    assert result.status == "resolved"
    assert result.url == f"{SITE}/products/g-short-double-navy"
