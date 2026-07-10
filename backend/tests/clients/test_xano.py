"""Unit tests for the Xano client: login auth + Tillin -> canonical mapping."""

import json
from decimal import Decimal
from typing import Any

import httpx
import pytest

from app.clients.xano import PRODUCTS_PATH, XanoClient, XanoError

# One realistic product in the Tillin `products_with_pagination` shape.
TILLIN_PRODUCT = {
    "id": 1911,
    "title": "Veste matelassée",
    "product_reference_code": "AW25-VM01",
    "brand_id": 1332,
    "season_id": 44,
    "category": {"id": 12, "title": "Vestes"},
    "product_variants": [
        {
            "id": 803248,
            "sku": "VM01-S",
            "barcode": "3600000000001",
            "weight": 0.8,
            "weight_unit": "1",
            # Retail price nested as `price.amount` (the live Tillin shape).
            "price": {"amount": "89.90", "currency": "EUR"},
            "product_image": {"src": "https://cdn.tillin/vm01-1.jpg", "position": 1},
        },
        {
            "id": 803249,
            "sku": "VM01-M",
            "barcode": None,
            "product_image": {"src": "https://cdn.tillin/vm01-1.jpg", "position": 1},
        },
    ],
    "product_images": [],
}


BRANDS = [
    {"id": 1332, "title": "Gramicci", "brand_website": "https://gramicci.co.uk"},
    {"id": 44, "title": "Multi", "website_urls": ["https://a.com", "https://b.com"]},
]


def _store(
    *,
    products: list[dict[str, Any]] | None = None,
    detail: dict[str, Any] | None = None,
    brands: list[dict[str, Any]] | None = None,
    categories: list[dict[str, Any]] | None = None,
    seasons: list[dict[str, Any]] | None = None,
    compositions: list[dict[str, Any]] | None = None,
    tags: list[dict[str, Any]] | None = None,
    data_source: str = "",
) -> httpx.MockTransport:
    """Fake Xano: /auth/login issues a token, reads require the bearer."""

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if data_source:
            assert request.headers.get("X-Data-Source") == data_source
        if path.endswith("/auth/login"):
            return httpx.Response(200, json={"authToken": "jwt-token"})
        assert request.headers.get("Authorization") == "Bearer jwt-token"
        if path.endswith("/brand"):
            return httpx.Response(200, json=BRANDS if brands is None else brands)
        if path.endswith("/get_all_informations"):
            return httpx.Response(
                200,
                json={
                    "company_all_informations": {
                        "categories": categories or [],
                        "seasons": seasons or [],
                        "compositions": compositions or [],
                        "tags": tags or [],
                    }
                },
            )
        if path.endswith(PRODUCTS_PATH):
            return httpx.Response(
                200,
                json={
                    "items": products or [],
                    "itemsTotal": len(products or []),
                    "curPage": 1,
                },
            )
        if "/product/" in path:
            return httpx.Response(200, json=detail) if detail else httpx.Response(404)
        return httpx.Response(404)

    return httpx.MockTransport(handler)


def _client(transport: httpx.MockTransport, *, data_source: str = "") -> XanoClient:
    return XanoClient(
        "https://tillin.test/api",
        email="svc@tillin.fr",
        password="secret",
        data_source=data_source,
        transport=transport,
    )


def test_search_maps_payload_and_sends_filters() -> None:
    captured: dict[str, httpx.Request] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path.endswith("/auth/login"):
            return httpx.Response(200, json={"authToken": "jwt-token"})
        if path.endswith("/brand"):
            return httpx.Response(200, json=BRANDS)
        captured["request"] = request  # only the products request
        return httpx.Response(200, json={"items": [TILLIN_PRODUCT], "itemsTotal": 1})

    with _client(httpx.MockTransport(handler)) as client:
        page = client.search_products(text="veste", brand=1332, page=2, per_page=10)

    request = captured["request"]
    assert request.headers["Authorization"] == "Bearer jwt-token"
    assert request.url.params["search_query_text"] == "veste"
    assert request.url.params["search_query_brand"] == "1332"
    assert request.url.params["external[page]"] == "2"
    assert request.url.params["external[per_page]"] == "10"

    assert page.total == 1
    product = page.items[0]
    assert product.id == 1911
    assert product.title == "Veste matelassée"
    assert product.reference_code == "AW25-VM01"
    assert product.category == "Vestes"
    assert [v.sku for v in product.variants] == ["VM01-S", "VM01-M"]
    assert product.variants[0].barcode == "3600000000001"
    # Nested `price.amount` -> variant price; product price = first priced variant.
    assert product.variants[0].price == Decimal("89.90")
    assert product.variants[1].price is None
    assert product.price == Decimal("89.90")
    # Images come from variants; the shared src is de-duplicated.
    assert [image.url for image in product.images] == ["https://cdn.tillin/vm01-1.jpg"]
    # Brand id resolved to name + website via the /brand map.
    assert product.brand is not None
    assert product.brand.id == 1332
    assert product.brand.name == "Gramicci"
    assert product.brand.website_urls == ["https://gramicci.co.uk"]


def test_brand_map_resolves_name_and_urls_both_shapes() -> None:
    # brand 1332 -> single `brand_website`; brand 44 -> `website_urls` list.
    one = {"id": 1, "brand_id": 1332, "product_variants": []}
    many = {"id": 2, "brand_id": 44, "product_variants": []}
    with _client(_store(products=[one, many])) as client:
        page = client.search_products()
    by_id = {p.id: p for p in page.items}
    assert by_id[1].brand is not None
    assert by_id[1].brand.website_urls == ["https://gramicci.co.uk"]
    assert by_id[2].brand is not None
    assert by_id[2].brand.website_urls == ["https://a.com", "https://b.com"]


def test_get_classification_normalizes_groups() -> None:
    company = {
        "brands": [{"id": 2, "title": "Zed"}, {"id": 1, "title": "Alpha"}],
        "categories": [{"id": 5, "title": "Shoes", "parent_id": 0}],
        "compositions": [
            {"id": 12, "title": "Laine", "active": True, "isVisible": True},
            {"id": 11, "title": "Coton", "active": True, "isVisible": True},
        ],
        "seasons": [{"id": 9, "title": None}, {"id": 8, "title": "SS25"}],
        "suppliers": [{"id": 3, "name": "ACME"}],  # suppliers use `name`
        "tags": [{"id": 7, "title": "New"}],
    }

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/auth/login"):
            return httpx.Response(200, json={"authToken": "jwt-token"})
        return httpx.Response(200, json={"company_all_informations": company})

    with _client(httpx.MockTransport(handler)) as client:
        filters = client.get_classification()

    # Sorted by title; suppliers `name` normalized to `title`.
    assert [b["title"] for b in filters["brands"]] == ["Alpha", "Zed"]
    assert filters["categories"][0] == {"id": 5, "title": "Shoes", "parent_id": 0}
    assert filters["suppliers"][0]["title"] == "ACME"
    # The season with title=None is dropped.
    assert [s["title"] for s in filters["seasons"]] == ["SS25"]
    # Compositions: normalized to {id, title} options, sorted by title.
    assert filters["compositions"] == [
        {"id": 11, "title": "Coton"},
        {"id": 12, "title": "Laine"},
    ]


def test_brand_map_failure_is_non_fatal() -> None:
    # /brand returns 500 -> products keep brand_id only, no raise.
    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path.endswith("/auth/login"):
            return httpx.Response(200, json={"authToken": "jwt-token"})
        if path.endswith("/brand"):
            return httpx.Response(500)
        return httpx.Response(200, json={"items": [TILLIN_PRODUCT], "itemsTotal": 1})

    with _client(httpx.MockTransport(handler)) as client:
        page = client.search_products()
    assert page.items[0].brand is not None
    assert page.items[0].brand.id == 1332
    assert page.items[0].brand.name is None
    assert page.items[0].brand.website_urls == []


def test_images_from_product_level_and_protocol_relative() -> None:
    # Product-level images come first; variant image is appended; URLs are
    # scheme-normalized (protocol-relative -> https).
    product = {
        "id": 178,
        "product_images": [
            {"src": "https://s3.host/img-a", "position": 1},
            {"src": "//cdn.host/img-b", "position": 2},
        ],
        "product_variants": [
            {"id": 1, "product_image": {"src": "https://s3.host/img-a"}},  # dup
            {"id": 2, "product_image": {"src": "//cdn.host/img-c"}},
        ],
    }
    with _client(_store(products=[product])) as client:
        page = client.search_products()
    assert [i.url for i in page.items[0].images] == [
        "https://s3.host/img-a",
        "https://cdn.host/img-b",
        "https://cdn.host/img-c",
    ]


def test_get_product_returns_detail_and_404_is_none() -> None:
    with _client(_store(detail=TILLIN_PRODUCT)) as client:
        product = client.get_product(1911)
    assert product is not None and product.id == 1911
    # The detail shape carries the same nested `price.amount` mapping.
    assert product.price == Decimal("89.90")
    assert [v.price for v in product.variants] == [Decimal("89.90"), None]

    with _client(_store(detail=None)) as client:
        assert client.get_product(9999) is None


def test_get_product_resolves_flat_category_id_via_classification() -> None:
    # The detail shape carries no nested `category`, only a flat `category_id`;
    # the title is resolved through the classification map.
    detail = {
        "id": 2680,
        "title": "Polo rayé",
        "brand_id": 1332,
        "category_id": 1465,
        "category_ids": [1465],
        "product_variants": [],
    }
    store = _store(detail=detail, categories=[{"id": 1465, "title": "Polos"}])
    with _client(store) as client:
        product = client.get_product(2680)
    assert product is not None
    assert product.category == "Polos"


def test_get_product_maps_season_department_composition_tags_and_variant_axes() -> None:
    # A realistic detail payload: flat classification ids + positional variant
    # options declared by `product_options` (Taille at position 1, Couleur at 2).
    detail = {
        "id": 1911,
        "title": "Sneakers",
        "brand_id": 1332,
        "category_id": 12,
        "season_id": 62,
        "department_id": 2,  # -> Femme (static map)
        "composition_id": 5,
        "tags_id": [7, 8, 99],  # 99 has no title -> dropped
        "manufacturing_country": "Portugal",
        "product_options": [
            {"name": "Couleur", "position": 2, "values": ["Bleu"]},
            {"name": "Taille", "position": 1, "values": ["41", "42"]},
        ],
        "product_variants": [
            {
                "id": 1,
                "sku": "S-41",
                "barcode": "3600000000001",
                "options": ["41", "Bleu"],  # aligned to position: [Taille, Couleur]
                "price": {"amount": "190", "currency_code_id": 1},
                "wholesale_price": {"amount": "87.7", "currency_code_id": 1},
                "weight": 0.72,
            },
        ],
    }
    store = _store(
        detail=detail,
        categories=[{"id": 12, "title": "Sneakers"}],
        seasons=[{"id": 62, "title": "FW24"}],
        compositions=[{"id": 5, "title": "Cuir"}],
        tags=[{"id": 7, "title": "Nouveauté"}, {"id": 8, "title": "Éco"}],
    )
    with _client(store) as client:
        product = client.get_product(1911)
    assert product is not None
    assert product.season == "FW24"
    assert product.department == "Femme"
    assert product.composition == "Cuir"
    assert product.manufacturing_country == "Portugal"
    assert product.tags == ["Nouveauté", "Éco"]
    variant = product.variants[0]
    assert variant.size == "41"
    assert variant.color == "Bleu"
    assert variant.price == Decimal("190")
    assert variant.wholesale_price == Decimal("87.7")


def test_upload_product_images_sends_repeated_files_and_maps_response() -> None:
    captured: dict[str, httpx.Request] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/auth/login"):
            return httpx.Response(200, json={"authToken": "jwt-token"})
        captured["request"] = request
        return httpx.Response(
            200,
            json={"images": [{"id": 9, "src": "//xano.test/x.jpg", "position": 3}]},
        )

    with _client(httpx.MockTransport(handler)) as client:
        created = client.upload_product_images(
            42,
            [
                ("a.jpg", b"\xff\xd8aaa", "image/jpeg"),
                ("b.png", b"\x89PNGbbb", "image/png"),
            ],
        )

    # Response mapped to canonical ProductImage (protocol-relative src fixed);
    # the Tillin `product_image.id` is kept for the replace-on-save flow.
    assert [(i.id, i.url, i.position) for i in created] == [
        (9, "https://xano.test/x.jpg", 3)
    ]
    request = captured["request"]
    assert request.url.path.endswith("/product_image/42/bulk")
    assert request.headers["content-type"].startswith("multipart/form-data")
    # Both files travel under a repeated `files` part (not collapsed to one).
    body = request.content
    assert b"a.jpg" in body and b"b.png" in body
    assert body.count(b'name="files"') == 2


def test_deactivate_product_images_puts_ids() -> None:
    captured: dict[str, httpx.Request] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/auth/login"):
            return httpx.Response(200, json={"authToken": "jwt-token"})
        captured["request"] = request
        return httpx.Response(200, json={"ok": True})

    with _client(httpx.MockTransport(handler)) as client:
        client.deactivate_product_images([501, 502])

    request = captured["request"]
    assert request.method == "PUT"
    assert request.url.path.endswith("/product_image/deactivate")
    assert json.loads(request.content) == {"product_image_ids": [501, 502]}


def test_deactivate_product_images_noop_on_empty_ids() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/auth/login"):
            return httpx.Response(200, json={"authToken": "jwt-token"})
        raise AssertionError("no request expected for empty ids")

    with _client(httpx.MockTransport(handler)) as client:
        client.deactivate_product_images([])  # returns without calling


def test_set_product_weight_posts_ids_weight_and_unit() -> None:
    captured: dict[str, httpx.Request] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/auth/login"):
            return httpx.Response(200, json={"authToken": "jwt-token"})
        captured["request"] = request
        return httpx.Response(200, json={"ok": True})

    with _client(httpx.MockTransport(handler)) as client:
        client.set_product_weight([1911, 1912], 0.5, "1")

    request = captured["request"]
    assert request.method == "PUT"  # POST collides with another route
    assert request.url.path.endswith("/product/weight")
    body = json.loads(request.content)
    assert body == {"product_ids": [1911, 1912], "weight_unit": "1", "weight": 0.5}


def test_set_product_weight_noop_on_empty_ids() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/auth/login"):
            return httpx.Response(200, json={"authToken": "jwt-token"})
        raise AssertionError("no request expected for empty ids")

    with _client(httpx.MockTransport(handler)) as client:
        client.set_product_weight([], 0.5)  # returns without calling


def test_get_product_category_is_none_when_classification_unavailable() -> None:
    # /get_all_informations failing must not break the detail read.
    detail = {"id": 2680, "title": "Polo", "category_id": 1465, "product_variants": []}

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path.endswith("/auth/login"):
            return httpx.Response(200, json={"authToken": "jwt-token"})
        if path.endswith("/get_all_informations"):
            return httpx.Response(500)
        if path.endswith("/brand"):
            return httpx.Response(200, json=BRANDS)
        return httpx.Response(200, json=detail)

    with _client(httpx.MockTransport(handler)) as client:
        product = client.get_product(2680)
    assert product is not None
    assert product.category is None


def test_data_source_header_is_sent() -> None:
    with _client(
        _store(products=[TILLIN_PRODUCT], data_source="test"), data_source="test"
    ) as client:
        page = client.search_products()
    assert page.total == 1


def test_token_is_reused_then_refreshed_on_401() -> None:
    login_count = {"n": 0}
    state = {"reject_next": False}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/auth/login"):
            login_count["n"] += 1
            return httpx.Response(200, json={"authToken": "jwt-token"})
        if state["reject_next"]:
            state["reject_next"] = False
            return httpx.Response(401)
        return httpx.Response(200, json={"items": [], "itemsTotal": 0})

    with _client(httpx.MockTransport(handler)) as client:
        client.search_products()  # logs in once
        client.search_products()  # reuses token — no second login
        assert login_count["n"] == 1
        state["reject_next"] = True
        client.search_products()  # 401 -> re-login -> retry
        assert login_count["n"] == 2


def test_write_methods_post_expected_bodies() -> None:
    calls: list[tuple[str, dict[str, Any]]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/auth/login"):
            return httpx.Response(200, json={"authToken": "jwt-token"})
        import json as _json

        calls.append((request.url.path, _json.loads(request.content)))
        return httpx.Response(200, json={"ok": True})

    with _client(httpx.MockTransport(handler)) as client:
        client.add_product_images(1911, ["https://a.jpg", "", "https://b.jpg"])
        client.enrich_product(1911, title="T", description="D", meta_description="M")
        # None fields are omitted; an all-None enrich sends nothing.
        client.enrich_product(1911, description="only-desc")
        client.enrich_product(1911)
        client.add_product_images(1911, [])  # no-op

    assert calls[0][0].endswith("/product_image/1911/bulk")
    assert calls[0][1] == {"image_urls": ["https://a.jpg", "https://b.jpg"]}
    assert calls[1][0].endswith("/product/1911/enrich")
    assert calls[1][1] == {"title": "T", "description": "D", "meta_description": "M"}
    assert calls[2][1] == {"description": "only-desc"}
    # The all-None enrich and empty-image calls made no extra requests.
    assert len(calls) == 3


def test_list_brands_maps_and_sorts_by_name() -> None:
    brands: list[dict[str, Any]] = [
        {"id": 3, "title": "zeta", "brand_website": "zeta.com"},
        {"id": 9},  # unnamed -> sorts last
        {"id": 1, "title": "Alpha", "website_urls": ["https://a.com", "b.com"]},
    ]
    with _client(_store(brands=brands)) as client:
        result = client.list_brands()

    assert [(b.id, b.name) for b in result] == [
        (1, "Alpha"),
        (3, "zeta"),
        (9, None),
    ]
    # URLs are scheme-normalized in both brand shapes.
    assert result[0].website_urls == ["https://a.com", "https://b.com"]
    assert result[1].website_urls == ["https://zeta.com"]
    assert result[2].website_urls == []


def test_list_brands_surfaces_upstream_errors() -> None:
    # Unlike the best-effort product-side brand map, this read must raise.
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/auth/login"):
            return httpx.Response(200, json={"authToken": "jwt-token"})
        return httpx.Response(500)

    with _client(httpx.MockTransport(handler)) as client:
        with pytest.raises(XanoError) as exc_info:
            client.list_brands()
    assert exc_info.value.status_code == 502


def test_set_brand_website_urls_normalizes_and_invalidates_cache() -> None:
    brand_reads = {"n": 0}
    captured: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path.endswith("/auth/login"):
            return httpx.Response(200, json={"authToken": "jwt-token"})
        if path.endswith("/brand/1332/website_urls"):
            import json as _json

            captured["body"] = _json.loads(request.content)
            return httpx.Response(200, json={"ok": True})
        if path.endswith("/brand"):
            brand_reads["n"] += 1
            return httpx.Response(200, json=BRANDS)
        return httpx.Response(200, json={"items": [], "itemsTotal": 0})

    with _client(httpx.MockTransport(handler)) as client:
        client.search_products()  # warms the brand cache
        client.search_products()  # cache hit — still one /brand read
        assert brand_reads["n"] == 1

        client.set_brand_website_urls(
            1332, [" gramicci.com ", "", "//cdn.gramicci.jp", "https://gramicci.co.uk/"]
        )
        assert captured["body"] == {
            "brand_id": 1332,
            "website_urls": [
                "https://gramicci.com",
                "https://cdn.gramicci.jp",
                "https://gramicci.co.uk",
            ],
        }

        client.search_products()  # cache was invalidated -> /brand re-fetched
        assert brand_reads["n"] == 2


def test_product_import_posts_multipart_csv() -> None:
    captured: dict[str, httpx.Request] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/auth/login"):
            return httpx.Response(200, json={"authToken": "jwt-token"})
        captured["request"] = request
        return httpx.Response(200, json={"ok": True})

    with _client(httpx.MockTransport(handler)) as client:
        result = client.product_import(
            file_name="import_l-espion_po-889.csv",
            csv_bytes=b"id,title\n,Pull marin\n",
            location_id=7,
        )

    assert result == {"ok": True}
    request = captured["request"]
    assert request.url.path.endswith("/product_import")
    assert request.headers["Authorization"] == "Bearer jwt-token"
    assert request.headers["Content-Type"].startswith("multipart/form-data")
    body = request.content
    # The CSV travels as the `file_import` part with its computed name...
    assert b'name="file_import"' in body
    assert b'filename="import_l-espion_po-889.csv"' in body
    assert b"Content-Type: text/csv" in body
    assert b"id,title\n,Pull marin\n" in body
    # ...and the target location as a plain form field.
    assert b'name="location_id"' in body
    assert b"\r\n\r\n7\r\n" in body


def test_product_import_retries_on_401_and_raises_on_error() -> None:
    login_count = {"n": 0}
    state = {"reject_next": True}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/auth/login"):
            login_count["n"] += 1
            return httpx.Response(200, json={"authToken": "jwt-token"})
        if state["reject_next"]:
            state["reject_next"] = False
            return httpx.Response(401)
        return httpx.Response(200, json={"ok": True})

    with _client(httpx.MockTransport(handler)) as client:
        client.product_import(file_name="a.csv", csv_bytes=b"x", location_id=1)
    # First attempt 401 -> re-login -> retry succeeded.
    assert login_count["n"] == 2

    def failing(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/auth/login"):
            return httpx.Response(200, json={"authToken": "jwt-token"})
        return httpx.Response(500)

    with _client(httpx.MockTransport(failing)) as client:
        with pytest.raises(XanoError) as exc_info:
            client.product_import(file_name="a.csv", csv_bytes=b"x", location_id=1)
    assert exc_info.value.status_code == 502


def test_list_locations_filters_third_party_and_sorts() -> None:
    # `origin` is an OBJECT {shop_domain, third_party, ...} in the live payload,
    # NOT a string — a non-empty third_party marks a marketplace feed.
    company = {
        "locations": [
            {
                "id": 3,
                "name": "Zeta Store",
                "origin": {"shop_domain": "", "third_party": ""},
            },
            {
                "id": 5,
                "name": "Marketplace",
                "origin": {"shop_domain": "x.myshopify.com", "third_party": "Shopify"},
            },
            {
                "id": 6,
                "name": "Feed",
                "origin": {"shop_domain": "y", "third_party": "Prestashop"},
            },
            {"id": 1, "name": "Alpha Shop"},  # no origin at all
            {"id": None, "name": "ignored"},
        ]
    }

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/auth/login"):
            return httpx.Response(200, json={"authToken": "jwt-token"})
        return httpx.Response(200, json={"company_all_informations": company})

    with _client(httpx.MockTransport(handler)) as client:
        locations = client.list_locations()

    assert locations == [
        {"id": 1, "title": "Alpha Shop"},
        {"id": 3, "title": "Zeta Store"},
    ]


def test_list_locations_empty_when_payload_malformed() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/auth/login"):
            return httpx.Response(200, json={"authToken": "jwt-token"})
        return httpx.Response(200, json={"unexpected": True})

    with _client(httpx.MockTransport(handler)) as client:
        assert client.list_locations() == []


def test_login_failure_raises() -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(403, json={"message": "nope"})

    with _client(httpx.MockTransport(handler)) as client, pytest.raises(XanoError):
        client.search_products()


def test_upstream_500_and_timeout_raise() -> None:
    def erroring(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/auth/login"):
            return httpx.Response(200, json={"authToken": "jwt-token"})
        return httpx.Response(500)

    with _client(httpx.MockTransport(erroring)) as client:
        with pytest.raises(XanoError) as exc_info:
            client.search_products()
    assert exc_info.value.status_code == 502

    def timing_out(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/auth/login"):
            return httpx.Response(200, json={"authToken": "jwt-token"})
        raise httpx.TimeoutException("slow", request=request)

    with _client(httpx.MockTransport(timing_out)) as client:
        with pytest.raises(XanoError) as exc_info:
            client.search_products()
    assert exc_info.value.status_code == 504
