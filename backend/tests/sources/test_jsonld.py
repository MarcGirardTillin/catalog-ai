"""Tests for the free schema.org/Product (JSON-LD) extraction."""

import httpx

from app.sources.jsonld import fetch_jsonld_product

URL = "https://brand.example/products/bag-dark-bronze"


def _client(html: str) -> httpx.Client:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text=html, headers={"content-type": "text/html"})

    return httpx.Client(transport=httpx.MockTransport(handler))


def test_extracts_product_node_with_identifiers_and_color() -> None:
    html = """
    <html><head><script type="application/ld+json">
    {"@context": "https://schema.org", "@type": "Product",
     "name": "Small Belted Hobo Bag",
     "description": "Sac en cuir.",
     "image": ["https://cdn.brand/1.jpg", {"url": "https://cdn.brand/2.jpg"}],
     "sku": "BG0223 LL0108_GR211_OS", "gtin13": "3666656578767",
     "color": "Dark Bronze",
     "offers": {"@type": "Offer", "price": "990"}}
    </script></head></html>
    """
    with _client(html) as client:
        product = fetch_jsonld_product(URL, client=client)

    assert product is not None
    assert product["title"] == "Small Belted Hobo Bag"
    assert product["body_html"] == "Sac en cuir."
    assert product["images"] == [
        {"src": "https://cdn.brand/1.jpg"},
        {"src": "https://cdn.brand/2.jpg"},
    ]
    # Ordre = _ID_KEYS (gtin* avant sku) — seul le contenu compte ici.
    assert set(product["_reference_codes"]) == {
        "BG0223 LL0108_GR211_OS",
        "3666656578767",
    }
    assert product["_color"] == "Dark Bronze"
    assert product["_jsonld"] is True
    assert product["variants"] == []


def test_product_in_graph_and_list_shapes() -> None:
    html = """
    <script type="application/ld+json">
    {"@graph": [{"@type": "WebSite", "name": "x"},
                {"@type": ["Product"], "name": "Veste", "sku": "V-1"}]}
    </script>
    """
    with _client(html) as client:
        product = fetch_jsonld_product(URL, client=client)
    assert product is not None and product["title"] == "Veste"


def test_returns_none_without_product_or_on_thin_node() -> None:
    with _client("<html><head></head></html>") as client:
        assert fetch_jsonld_product(URL, client=client) is None
    # Un Product sans identifiant, ni image, ni description est trop pauvre.
    thin = (
        '<script type="application/ld+json">{"@type": "Product", "name": "X"}</script>'
    )
    with _client(thin) as client:
        assert fetch_jsonld_product(URL, client=client) is None


def test_returns_none_on_error_or_non_html() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(404)

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        assert fetch_jsonld_product(URL, client=client) is None
