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


def _store(
    *,
    products: list[dict] | None = None,
    detail: dict | None = None,
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
        if request.url.path.endswith("/auth/login"):
            return httpx.Response(200, json={"authToken": "jwt-token"})
        captured["request"] = request
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
    assert product.brand is not None and product.brand.id == 1332
    assert product.category == "Vestes"
    assert [v.sku for v in product.variants] == ["VM01-S", "VM01-M"]
    assert product.variants[0].barcode == "3600000000001"
    # Images come from variants; the shared src is de-duplicated.
    assert [image.url for image in product.images] == ["https://cdn.tillin/vm01-1.jpg"]


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
