"""Unit tests for the Xano client transport and Tillin -> canonical mapping."""

import httpx
import pytest

from app.clients.xano import PRODUCTS_PATH, XanoClient, XanoError


def _client(handler: httpx.MockTransport) -> XanoClient:
    return XanoClient(
        base_url="https://tillin.test/api",
        token="secret-token",
        transport=handler,
    )


def test_maps_tillin_payload_to_canonical_products() -> None:
    captured: dict[str, httpx.Request] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["request"] = request
        return httpx.Response(
            200,
            json={
                "items": [
                    {
                        "id": 101,
                        "name": "Gramicci G-Shorts",
                        "product_reference_code": "SS25-080T",
                        "brand": {
                            "id": 7,
                            "name": "Gramicci",
                            "website_urls": ["https://gramicci.co.uk"],
                        },
                        "season": "SS25",
                        "category": "Shorts",
                        "department": "Men",
                        "product_variants": [
                            {
                                "id": 9001,
                                "sku": "TIL-1",
                                "product_variant_barcode": "5012345678900",
                                "weight": 0.3,
                                "weight_unit": "kg",
                            }
                        ],
                        "product_images": [
                            {"url": "https://img/1.jpg", "position": 1},
                            "https://img/2.jpg",
                        ],
                    }
                ],
                "itemsTotal": 1,
            },
        )

    with _client(httpx.MockTransport(handler)) as client:
        page = client.list_products(tag="ss25", page=1, per_page=20)

    request = captured["request"]
    assert request.headers["Authorization"] == "Bearer secret-token"
    assert request.url.path.endswith(PRODUCTS_PATH)
    assert request.url.params["tag"] == "ss25"

    assert page.total == 1
    product = page.items[0]
    assert product.id == 101
    assert product.title == "Gramicci G-Shorts"
    assert product.reference_code == "SS25-080T"
    assert product.brand is not None
    assert product.brand.website_urls == ["https://gramicci.co.uk"]
    assert product.variants[0].barcode == "5012345678900"
    # One image from a dict, one from a bare URL string.
    assert [image.url for image in product.images] == [
        "https://img/1.jpg",
        "https://img/2.jpg",
    ]


def test_ids_are_passed_and_bare_list_payload_is_supported() -> None:
    captured: dict[str, httpx.Request] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["request"] = request
        return httpx.Response(200, json=[{"id": 1}, {"id": 2}])

    with _client(httpx.MockTransport(handler)) as client:
        page = client.list_products(ids=[1, 2])

    assert captured["request"].url.params["ids"] == "1,2"
    assert page.total == 2
    # A product with only an id maps with empty/None defaults.
    assert page.items[0].title is None
    assert page.items[0].variants == []


def test_upstream_error_status_becomes_xano_error() -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(500, json={"message": "boom"})

    with _client(httpx.MockTransport(handler)) as client:
        with pytest.raises(XanoError) as exc_info:
            client.list_products(tag="x")

    assert exc_info.value.status_code == 502
    assert exc_info.value.code == "xano_error"


def test_timeout_becomes_504_xano_timeout() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.TimeoutException("slow", request=request)

    with _client(httpx.MockTransport(handler)) as client:
        with pytest.raises(XanoError) as exc_info:
            client.list_products(tag="x")

    assert exc_info.value.status_code == 504
    assert exc_info.value.code == "xano_timeout"
