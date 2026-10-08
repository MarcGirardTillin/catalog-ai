"""Recherche interne des sites non-Shopify (vécu Le Petit Souk, Magento 2)."""

import json
from collections.abc import Callable

import httpx

from app.api.schemas import Product, ProductVariant
from app.clients.firecrawl import FirecrawlClient
from app.sources.resolver import resolve_source_url

SITE = "https://www.petitsouk.example"
BARCODE = "5555500381937"

PRODUCT = Product(
    id=1,
    title="Déguisement Enfant Chevalier",
    reference_code="38193",
    variants=[ProductVariant(id=1, barcode=BARCODE)],
)

HOME = """<html><head>
<script type="text/x-magento-init">{}</script>
<script type="application/ld+json">{"@context":"https://schema.org",
"@type":"WebSite","url":"https://www.petitsouk.example/",
"potentialAction":{"@type":"SearchAction",
"target":"https://www.petitsouk.example/catalogsearch/result/?q={search_term_string}",
"query-input":"required name=search_term_string"}}</script>
</head><body>home</body></html>"""


def _product_page(title: str, sku: str, image: str) -> str:
    jsonld = {
        "@context": "https://schema.org",
        "@type": "Product",
        "name": title,
        "sku": image,
        "image": f"{SITE}/media{image}",
        "description": "Un déguisement.",
    }
    return (
        "<html><head>"
        f'<script type="application/ld+json">{json.dumps(jsonld)}</script>'
        f'</head><body><form data-product-sku="{sku}"></form></body></html>'
    )


GOOD_PAGE = _product_page(
    "Déguisement enfant chevalier", BARCODE, "/3/8/38193-costume-chevalier.jpg"
)
# Fiche sœur : code de lot « W-<ean> » — ne doit PAS matcher le barcode.
SIBLING_PAGE = _product_page(
    "Ensemble déguisement enfant chevalier",
    f"W-{BARCODE}",
    "/e/n/ensemble-costume-chevalier.png",
)


def _results(*paths: str) -> str:
    items = "".join(
        f'<li><a class="product-item-link" href="{SITE}{path}">x</a></li>'
        for path in paths
    )
    return f"<html><body><ol>{items}</ol></body></html>"


def _magento(
    search: Callable[[str], httpx.Response],
    pages: dict[str, str],
    seen: list[str] | None = None,
) -> httpx.MockTransport:
    """Fake Magento site: suggest.json 404, home with SearchAction, search
    answered by ``search(query)``, product pages by path."""

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if seen is not None:
            seen.append(path)
        if path == "/search/suggest.json":
            return httpx.Response(404, text="<html>404</html>")
        if path in {"", "/"}:
            return httpx.Response(200, html=HOME)
        if path == "/catalogsearch/result/":
            return search(request.url.params["q"])
        if path in pages:
            return httpx.Response(200, html=pages[path])
        return httpx.Response(404, text="<html>404</html>")

    return httpx.MockTransport(handler)


def _forbidden_firecrawl() -> FirecrawlClient:
    def handler(_request: httpx.Request) -> httpx.Response:
        raise AssertionError("firecrawl must not be called")

    return FirecrawlClient("fc-key", transport=httpx.MockTransport(handler))


def test_search_redirecting_to_barcode_page_resolves_at_one() -> None:
    def search(query: str) -> httpx.Response:
        if query == BARCODE:
            return httpx.Response(
                302, headers={"Location": f"{SITE}/p/deguisement-enfant-chevalier.html"}
            )
        return httpx.Response(200, html=_results())

    transport = _magento(search, {"/p/deguisement-enfant-chevalier.html": GOOD_PAGE})
    with (
        _forbidden_firecrawl() as firecrawl,
        httpx.Client(transport=transport) as client,
    ):
        result = resolve_source_url(client, PRODUCT, [SITE], firecrawl=firecrawl)

    assert result.status == "resolved"
    assert result.method_used == "site_search"
    assert result.score == 1.0
    assert result.matched_by == "barcode"
    assert result.url == f"{SITE}/p/deguisement-enfant-chevalier.html"
    # Le JSON-LD déjà lu sert de fiche source (aucun fetch de plus).
    assert result.source_product is not None
    assert result.source_product["title"] == "Déguisement enfant chevalier"


def test_results_page_picks_the_page_carrying_the_barcode() -> None:
    def search(_query: str) -> httpx.Response:
        # La fiche sœur arrive EN PREMIER dans les résultats.
        return httpx.Response(
            200,
            html=_results(
                "/p/ensemble-deguisement-enfant-chevalier.html",
                "/p/deguisement-enfant-chevalier.html",
            ),
        )

    transport = _magento(
        search,
        {
            "/p/ensemble-deguisement-enfant-chevalier.html": SIBLING_PAGE,
            "/p/deguisement-enfant-chevalier.html": GOOD_PAGE,
        },
    )
    with httpx.Client(transport=transport) as client:
        result = resolve_source_url(client, PRODUCT, [SITE])

    assert result.status == "resolved"
    assert result.method_used == "site_search"
    assert result.score == 1.0
    assert result.url == f"{SITE}/p/deguisement-enfant-chevalier.html"
    sibling = next(c for c in result.candidates if "ensemble" in c.url)
    assert sibling.score < 0.75


def test_page_without_barcode_but_reference_resolves_at_point_nine() -> None:
    page = _product_page(
        "Déguisement enfant chevalier", "MAG-1", "/3/8/38193-costume-chevalier.jpg"
    )

    def search(query: str) -> httpx.Response:
        if query == "38193":
            return httpx.Response(200, html=_results("/p/chevalier.html"))
        return httpx.Response(200, html=_results())

    transport = _magento(search, {"/p/chevalier.html": page})
    with httpx.Client(transport=transport) as client:
        result = resolve_source_url(client, PRODUCT, [SITE])

    assert result.status == "resolved"
    assert result.method_used == "site_search"
    assert result.score == 0.9
    assert result.url == f"{SITE}/p/chevalier.html"
    assert result.matched_by == "reference"


def test_unverified_page_stays_a_review_candidate() -> None:
    page = _product_page("Robe de princesse", "MAG-2", "/r/o/robe.jpg")

    def search(_query: str) -> httpx.Response:
        return httpx.Response(200, html=_results("/p/robe.html"))

    transport = _magento(search, {"/p/robe.html": page})
    with httpx.Client(transport=transport) as client:
        result = resolve_source_url(client, PRODUCT, [SITE])

    assert result.status == "needs_manual"
    assert result.url is None
    assert [c.url for c in result.candidates] == [f"{SITE}/p/robe.html"]
    assert result.candidates[0].score < 0.75
    assert (
        result.reason == "web search found pages but none matched the product reference"
    )


def test_shopify_site_behaviour_is_unchanged() -> None:
    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request.url.path)
        if request.url.path == "/search/suggest.json":
            return httpx.Response(
                200,
                json={
                    "resources": {"results": {"products": [{"handle": "chevalier"}]}}
                },
            )
        if request.url.path == "/products/chevalier.json":
            return httpx.Response(
                200,
                json={
                    "product": {
                        "title": "Chevalier",
                        "handle": "chevalier",
                        "variants": [{"sku": "X", "barcode": BARCODE}],
                    }
                },
            )
        return httpx.Response(404)

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        result = resolve_source_url(client, PRODUCT, [SITE])

    assert result.status == "resolved"
    assert result.method_used == "shopify_json"
    assert seen == ["/search/suggest.json", "/products/chevalier.json"]


def test_shopify_without_match_never_runs_site_search() -> None:
    """Une boutique Shopify (suggest.json JSON) sans résultat n'est PAS
    marquée non-Shopify : aucun GET de recherche interne."""
    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request.url.path)
        if request.url.path == "/search/suggest.json":
            return httpx.Response(
                200, json={"resources": {"results": {"products": []}}}
            )
        return httpx.Response(404)

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        result = resolve_source_url(client, PRODUCT, [SITE])

    assert result.status == "needs_manual"
    assert set(seen) == {"/search/suggest.json"}


def test_non_shopify_detection_is_cached_per_host() -> None:
    seen: list[str] = []

    def search(_query: str) -> httpx.Response:
        return httpx.Response(
            302, headers={"Location": f"{SITE}/p/deguisement-enfant-chevalier.html"}
        )

    transport = _magento(
        search, {"/p/deguisement-enfant-chevalier.html": GOOD_PAGE}, seen
    )
    with httpx.Client(transport=transport) as client:
        first = resolve_source_url(client, PRODUCT, [SITE])
        second = resolve_source_url(client, PRODUCT, [SITE])

    assert first.status == second.status == "resolved"
    # Un seul suggest.json (le 404 marque l'hôte) et une seule page d'accueil.
    assert seen.count("/search/suggest.json") == 1
    assert seen.count("/") + seen.count("") == 1


def test_pinned_shopify_json_never_runs_site_search() -> None:
    seen: list[str] = []
    transport = _magento(lambda _q: httpx.Response(200, html=_results()), {}, seen)
    with httpx.Client(transport=transport) as client:
        result = resolve_source_url(client, PRODUCT, [SITE], method="shopify_json")

    assert result.status == "needs_manual"
    assert "/catalogsearch/result/" not in seen


def test_unknown_platform_without_search_action_is_not_guessed() -> None:
    """Sans SearchAction ni plateforme reconnue : aucun gabarit deviné (une
    URL qui ignore la requête renverrait la home et ses produits en avant)."""
    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request.url.path)
        if request.url.path in {"", "/"}:
            return httpx.Response(200, html="<html><body>vitrine</body></html>")
        return httpx.Response(404, text="<html>404</html>")

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        result = resolve_source_url(client, PRODUCT, [SITE])

    assert result.status == "needs_manual"
    assert all(not path.startswith(("/catalogsearch", "/wp-json")) for path in seen)


def test_woocommerce_store_api_hit_matches_on_reference() -> None:
    woo = "https://shop.woo.example"
    product = Product(
        id=4,
        title="Bonnet marin",
        reference_code="BASUN252227",
        variants=[ProductVariant(id=1, barcode="3666666666666")],
    )
    page_url = f"{woo}/shop/bonnet-marin/"

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path == "/search/suggest.json":
            return httpx.Response(200, html="<html>wordpress</html>")
        if path == "/":
            return httpx.Response(
                200, html="<html><body class='woocommerce'>home</body></html>"
            )
        if path == "/wp-json/wc/store/v1/products":
            if request.url.params["search"] == "BASUN252227":
                return httpx.Response(
                    200,
                    json=[
                        {
                            "type": "variable",
                            "permalink": page_url,
                            "sku": "BASUN252227-OS",
                        }
                    ],
                )
            return httpx.Response(200, json=[])
        if path == "/shop/bonnet-marin/":
            return httpx.Response(
                200,
                html='<html><head><meta property="og:type" content="product">'
                '<meta property="og:title" content="Bonnet marin"></head></html>',
            )
        return httpx.Response(404)

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        result = resolve_source_url(client, product, [woo])

    assert result.status == "resolved"
    assert result.method_used == "site_search"
    assert result.score == 0.9
    assert result.url == page_url
    # Pas de JSON-LD sur la fiche : le pipeline la récupérera lui-même.
    assert result.source_product is None
