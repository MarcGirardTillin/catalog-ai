"""Tests for the shopify_json matcher and the source resolver."""

import json
from typing import Any

import httpx

from app.api.schemas import Brand, Product, ProductVariant
from app.clients.firecrawl import FirecrawlClient
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


def test_reference_match_ignores_formatting() -> None:
    """Vécu Lemaire : Tillin « BG0223 LL0108 » vs SKU site
    « BG0223 LL0108_GR211_OS » (et variantes à tirets) — le matching doit être
    insensible aux espaces/underscores/tirets."""
    candidate = {
        "title": "Small Belted Hobo Bag in Leather",
        "handle": "small-belted-hobo-bag",
        "tags": "",
        "variants": [{"sku": "BG0223 LL0108_GR211_OS", "barcode": ""}],
    }
    for reference in ("BG0223 LL0108", "bg0223-ll0108", "BG0223LL0108"):
        product = Product(id=5, title="Small Belted Hobo Bag", reference_code=reference)
        assert score_product_match(product, candidate) == 0.75, reference


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


def test_non_shopify_site_returning_html_degrades_instead_of_crashing() -> None:
    """Vu en prod (marque On) : un site NON-Shopify répond 200 avec du HTML
    sur /search/suggest.json — le JSONDecodeError tuait l'item entier."""
    html_site = "https://www.on-running.example"
    real_store = _store({"g-short-double-navy": GOOD_CANDIDATE})

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "www.on-running.example":
            return httpx.Response(200, text="<!doctype html><html>challenge</html>")
        return real_store.handle_request(request)

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        # Seul le site HTML : dégradation propre, pas d'exception.
        alone = resolve_source_url(client, PRODUCT, [html_site])
        # HTML + vrai store : le vrai store gagne quand même.
        both = resolve_source_url(client, PRODUCT, [html_site, SITE])

    assert alone.status == "needs_manual"
    assert both.status == "resolved"
    assert both.url == f"{SITE}/products/g-short-double-navy"


# ---------------------------------------------------------------------------
# Départage par couleur (chaîne Shopify) — coloris frères à référence partagée.
# ---------------------------------------------------------------------------

# Deux coloris du même modèle : même titre, même code modèle dans le SKU,
# seule la couleur diffère (cas Lemaire réel, formats simplifiés).
_BRONZE = {
    "title": "Small Belted Hobo Bag in Leather",
    "handle": "small-belted-hobo-bag-dark-bronze",
    "tags": "",
    "variants": [{"sku": "BG0223 LL0108_GR211_OS", "barcode": "111"}],
}
_CHOCOLATE = {
    "title": "Small Belted Hobo Bag in Leather",
    "handle": "small-belted-hobo-bag-dark-chocolate",
    "tags": "",
    "variants": [{"sku": "BG0223 LL0108_BR490_OS", "barcode": "222"}],
}


def _lemaire_product(color: str | None) -> Product:
    return Product(
        id=9,
        title="Small Belted Hobo Bag in Leather",
        reference_code="BG0223 LL0108",
        variants=[ProductVariant(id=1, color=color, size="OS")],
    )


def test_shopify_color_breaks_reference_tie() -> None:
    transport = _store(
        {
            "small-belted-hobo-bag-dark-chocolate": _CHOCOLATE,
            "small-belted-hobo-bag-dark-bronze": _BRONZE,
        }
    )
    with httpx.Client(transport=transport) as client:
        result = resolve_source_url(client, _lemaire_product("Dark Bronze"), [SITE])

    assert result.status == "resolved"
    assert result.url == f"{SITE}/products/small-belted-hobo-bag-dark-bronze"


def test_shopify_reference_tie_without_color_match_needs_manual() -> None:
    """Tous les coloris partagent la référence mais aucun ne porte la couleur
    du produit : ne pas choisir avec assurance."""
    transport = _store(
        {
            "small-belted-hobo-bag-dark-chocolate": _CHOCOLATE,
            "small-belted-hobo-bag-dark-bronze": _BRONZE,
        }
    )
    with httpx.Client(transport=transport) as client:
        result = resolve_source_url(client, _lemaire_product("Chianti"), [SITE])

    assert result.status == "needs_manual"
    assert result.reason == "pages match the reference but not the product color"
    assert len(result.candidates) == 2


def test_shopify_reference_tie_without_product_color_keeps_first() -> None:
    """Sans couleur produit (ou multi-coloris), comportement historique."""
    transport = _store({"small-belted-hobo-bag-dark-chocolate": _CHOCOLATE})
    with httpx.Client(transport=transport) as client:
        result = resolve_source_url(client, _lemaire_product(None), [SITE])

    assert result.status == "resolved"
    assert result.url == f"{SITE}/products/small-belted-hobo-bag-dark-chocolate"


# ---------------------------------------------------------------------------
# Firecrawl fallback (plan Phase 3) — search + structured extraction, capped.
# ---------------------------------------------------------------------------


def _firecrawl_store(
    pages: dict[str, dict[str, Any]], seen: list[httpx.Request] | None = None
) -> FirecrawlClient:
    """Fake Firecrawl: search returns every catalog page on the queried host,
    scrape (JSON mode) returns the page's extracted product."""

    def handler(request: httpx.Request) -> httpx.Response:
        if seen is not None:
            seen.append(request)
        body = json.loads(request.content)
        if request.url.path == "/v2/search":
            host = body["query"].split()[0].removeprefix("site:")
            hits = [
                {"url": url, "title": page.get("title")}
                for url, page in pages.items()
                if httpx.URL(url).host == host
            ]
            return httpx.Response(200, json={"success": True, "data": {"web": hits}})
        if request.url.path == "/v2/scrape":
            page = pages.get(body["url"])
            data: dict[str, Any] = {"metadata": {}}
            if page is not None:
                data["json"] = page
            return httpx.Response(200, json={"success": True, "data": data})
        return httpx.Response(404)

    return FirecrawlClient("fc-key", transport=httpx.MockTransport(handler))


def _forbidden_firecrawl() -> FirecrawlClient:
    def handler(_request: httpx.Request) -> httpx.Response:
        raise AssertionError("firecrawl must not be called")

    return FirecrawlClient("fc-key", transport=httpx.MockTransport(handler))


NON_SHOPIFY_SITE = "https://salomon.example"

EXTRACTED_MATCH = {
    "title": "G-Short Double Navy",
    "description": "Ref. G5FU-T081 — le short d'origine.",
    "images": ["https://salomon.example/img/1.jpg"],
    "reference_codes": ["G5FU-T081"],
}

EXTRACTED_DECOY = {
    "title": "Ridge Pant Olive",
    "description": "Un pantalon.",
    "images": [],
    "reference_codes": ["ZZZ-000"],
}


def test_auto_falls_back_to_firecrawl_and_resolves_on_reference() -> None:
    recorded: list[int] = []
    with (
        _firecrawl_store(
            {f"{NON_SHOPIFY_SITE}/fiche/g-short": EXTRACTED_MATCH}
        ) as firecrawl,
        # The brand site is not Shopify: suggest.json and product JSON 404.
        httpx.Client(transport=_store({})) as client,
    ):
        result = resolve_source_url(
            client,
            PRODUCT,
            [NON_SHOPIFY_SITE],
            firecrawl=firecrawl,
            usage_recorder=recorded.append,
        )

    assert result.status == "resolved"
    assert result.url == f"{NON_SHOPIFY_SITE}/fiche/g-short"
    assert result.score == 0.9
    assert result.method_used == "firecrawl"
    # The extraction is carried to the pipeline (no second paid extract) but
    # stays out of the serialized result (resolution_json).
    assert result.source_product is not None
    assert result.source_product["images"] == [
        {"src": "https://salomon.example/img/1.jpg"}
    ]
    assert "source_product" not in result.model_dump()
    # Metering: one search (2 credits) then one extract (5 credits).
    assert recorded == [2, 5]


def test_firecrawl_needs_manual_when_no_reference_match() -> None:
    with (
        _firecrawl_store(
            {f"{NON_SHOPIFY_SITE}/fiche/ridge-pant": EXTRACTED_DECOY}
        ) as firecrawl,
        httpx.Client(transport=_store({})) as client,
    ):
        result = resolve_source_url(
            client, PRODUCT, [NON_SHOPIFY_SITE], firecrawl=firecrawl
        )

    assert result.status == "needs_manual"
    # Raison affichée au reviewer : neutre, jamais le nom du prestataire.
    assert result.reason is not None and "firecrawl" not in result.reason.lower()
    assert "web search" in result.reason
    assert [(c.score, c.title) for c in result.candidates] == [
        (0.3, "Ridge Pant Olive")
    ]


def test_method_firecrawl_skips_shopify_entirely() -> None:
    shopify_calls: list[httpx.Request] = []

    def shopify_handler(request: httpx.Request) -> httpx.Response:
        shopify_calls.append(request)
        return httpx.Response(404)

    with (
        _firecrawl_store(
            {f"{NON_SHOPIFY_SITE}/fiche/g-short": EXTRACTED_MATCH}
        ) as firecrawl,
        httpx.Client(transport=httpx.MockTransport(shopify_handler)) as client,
    ):
        result = resolve_source_url(
            client, PRODUCT, [NON_SHOPIFY_SITE], method="firecrawl", firecrawl=firecrawl
        )

    assert result.status == "resolved"
    assert result.method_used == "firecrawl"
    assert shopify_calls == []


def test_method_shopify_json_never_touches_firecrawl() -> None:
    with (
        _forbidden_firecrawl() as firecrawl,
        httpx.Client(transport=_store({})) as client,
    ):
        result = resolve_source_url(
            client, PRODUCT, [SITE], method="shopify_json", firecrawl=firecrawl
        )

    assert result.status == "needs_manual"
    assert result.method_used is None


def test_auto_resolved_by_shopify_never_touches_firecrawl() -> None:
    with (
        _forbidden_firecrawl() as firecrawl,
        httpx.Client(
            transport=_store({"g-short-double-navy": GOOD_CANDIDATE})
        ) as client,
    ):
        result = resolve_source_url(client, PRODUCT, [SITE], firecrawl=firecrawl)

    assert result.status == "resolved"
    assert result.method_used == "shopify_json"


def test_firecrawl_extracts_are_capped_at_two() -> None:
    """Cost control: no matter how many hits/sites, at most 2 extract calls."""
    other_site = "https://other.example"
    pages = {
        f"{NON_SHOPIFY_SITE}/fiche/a": EXTRACTED_DECOY,
        f"{NON_SHOPIFY_SITE}/fiche/b": EXTRACTED_DECOY,
        f"{NON_SHOPIFY_SITE}/fiche/c": EXTRACTED_DECOY,
        f"{other_site}/fiche/d": EXTRACTED_MATCH,
    }
    seen: list[httpx.Request] = []
    recorded: list[int] = []
    with (
        _firecrawl_store(pages, seen) as firecrawl,
        httpx.Client(transport=_store({})) as client,
    ):
        result = resolve_source_url(
            client,
            PRODUCT,
            [NON_SHOPIFY_SITE, other_site],
            method="firecrawl",
            firecrawl=firecrawl,
            usage_recorder=recorded.append,
        )

    scrapes = [r for r in seen if r.url.path == "/v2/scrape"]
    assert len(scrapes) == 2  # first two on-host hits only — cap holds
    assert result.status == "needs_manual"
    assert recorded == [2, 5, 5]


def test_firecrawl_skips_barcode_queries_in_web_search() -> None:
    queries: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        if request.url.path == "/v2/search":
            queries.append(body["query"])
            return httpx.Response(200, json={"success": True, "data": {"web": []}})
        raise AssertionError("no extract expected")

    with (
        FirecrawlClient("fc-key", transport=httpx.MockTransport(handler)) as firecrawl,
        httpx.Client(transport=_store({})) as client,
    ):
        result = resolve_source_url(
            client, PRODUCT, [NON_SHOPIFY_SITE], method="firecrawl", firecrawl=firecrawl
        )

    assert result.status == "needs_manual"
    assert queries == [
        "site:salomon.example G5FU-T081",
        "site:salomon.example Gramicci G-Short Double Navy",
    ]


def test_firecrawl_reference_match_with_wrong_color_is_not_auto_resolved() -> None:
    """Le code modèle est partagé entre coloris : un match référence sur une
    page qui ne porte nulle part la couleur du produit reste un candidat à
    vérifier (0,5) — et la page au bon coloris, extraite ensuite, gagne."""
    product = Product(
        id=9,
        title="Small Belted Hobo Bag in Leather",
        reference_code="BG0223 LL0108",
        variants=[ProductVariant(id=1, color="Dark Bronze", size="OS")],
    )
    shared_ref = {
        "title": "Small Belted Hobo Bag in Leather",
        "description": "Ref. BG0223 LL0108.",
        "images": [],
        "reference_codes": ["BG0223 LL0108"],
    }
    chocolate_url = f"{NON_SHOPIFY_SITE}/products/hobo-bag-dark-chocolate"
    bronze_url = f"{NON_SHOPIFY_SITE}/products/hobo-bag-dark-bronze"

    # 1. Les deux pages remontent : chocolate (mauvais coloris, référence OK)
    # extraite en premier ne court-circuite plus ; bronze résout à 0,9.
    with (
        _firecrawl_store({chocolate_url: shared_ref, bronze_url: shared_ref}) as fc,
        httpx.Client(transport=_store({})) as client,
    ):
        both = resolve_source_url(
            client, product, [NON_SHOPIFY_SITE], method="firecrawl", firecrawl=fc
        )
    assert both.status == "resolved"
    assert both.url == bronze_url
    assert {(c.url, c.score) for c in both.candidates} >= {(chocolate_url, 0.5)}

    # 2. Seul le mauvais coloris existe : à vérifier, raison couleur.
    with (
        _firecrawl_store({chocolate_url: shared_ref}) as fc,
        httpx.Client(transport=_store({})) as client,
    ):
        wrong_only = resolve_source_url(
            client, product, [NON_SHOPIFY_SITE], method="firecrawl", firecrawl=fc
        )
    assert wrong_only.status == "needs_manual"
    assert wrong_only.reason == "pages match the reference but not the product color"
    assert [(c.url, c.score) for c in wrong_only.candidates] == [(chocolate_url, 0.5)]

    # 3. Sans couleur produit connue : le match référence garde son autorité.
    colorless = product.model_copy(
        update={"variants": [ProductVariant(id=1, size="OS")]}
    )
    with (
        _firecrawl_store({chocolate_url: shared_ref}) as fc,
        httpx.Client(transport=_store({})) as client,
    ):
        legacy = resolve_source_url(
            client, colorless, [NON_SHOPIFY_SITE], method="firecrawl", firecrawl=fc
        )
    assert legacy.status == "resolved"
    assert legacy.score == 0.9


def test_web_search_adds_single_color_to_title_query() -> None:
    """Une boutique travaille souvent une fiche par couleur : la couleur (quand
    elle est unique et absente du titre) précise la requête titre — vécu
    Lemaire : bon modèle, mauvais coloris (dark chocolate vs dark bronze)."""
    queries: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        if request.url.path == "/v2/search":
            queries.append(body["query"])
            return httpx.Response(200, json={"success": True, "data": {"web": []}})
        raise AssertionError("no extract expected")

    product = Product(
        id=3,
        title="Small Belted Hobo Bag in Leather",
        reference_code=None,
        variants=[
            ProductVariant(id=1, color="Dark Bronze", size="S"),
            ProductVariant(id=2, color="Dark Bronze", size="M"),
        ],
    )
    multi_color = product.model_copy(
        update={
            "variants": [
                ProductVariant(id=1, color="Dark Bronze"),
                ProductVariant(id=2, color="Dark Chocolate"),
            ]
        }
    )
    with (
        FirecrawlClient("fc-key", transport=httpx.MockTransport(handler)) as firecrawl,
        httpx.Client(transport=_store({})) as client,
    ):
        resolve_source_url(
            client, product, [NON_SHOPIFY_SITE], method="firecrawl", firecrawl=firecrawl
        )
        single = list(queries)
        queries.clear()
        resolve_source_url(
            client,
            multi_color,
            [NON_SHOPIFY_SITE],
            method="firecrawl",
            firecrawl=firecrawl,
        )

    assert single == [
        "site:salomon.example Small Belted Hobo Bag in Leather Dark Bronze",
        "site:salomon.example Small Belted Hobo Bag in Leather",
    ]
    # Couleur ambiguë (plusieurs coloris) : ne pas biaiser la recherche.
    assert queries == ["site:salomon.example Small Belted Hobo Bag in Leather"]
