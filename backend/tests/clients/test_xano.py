"""Unit tests for the Xano client: login auth + Tillin -> canonical mapping."""

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
    products: list[dict] | None = None,
    detail: dict | None = None,
    brands: list[dict] | None = None,
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

    with _client(_store(detail=None)) as client:
        assert client.get_product(9999) is None


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
    calls: list[tuple[str, dict]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/auth/login"):
            return httpx.Response(200, json={"authToken": "jwt-token"})
        import json as _json

        calls.append((request.url.path, _json.loads(request.content)))
        return httpx.Response(200, json={"ok": True})

    with _client(httpx.MockTransport(handler)) as client:
        client.add_product_images(1911, ["https://a.jpg", "", "https://b.jpg"])
        client.enrich_product(
            1911, title="T", description="D", meta_description="M"
        )
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
