"""Tests for the /products routes (auth + Xano dependency mocked)."""

import io
from collections.abc import Callable, Iterator
from decimal import Decimal
from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient
from PIL import Image

from app.api.deps import get_xano_client
from app.clients.xano import XanoClient
from app.main import app

Handler = Callable[[httpx.Request], httpx.Response]
InstallXano = Callable[[Handler], None]


def _image_bytes(image_format: str) -> bytes:
    """Vraie image encodée : la route décode les octets déposés."""
    buffer = io.BytesIO()
    Image.new("RGB", (10, 8), (10, 120, 200)).save(buffer, format=image_format)
    return buffer.getvalue()


@pytest.fixture
def override_xano() -> Iterator[InstallXano]:
    """Install a Xano client backed by a MockTransport for the dependency."""
    clients: list[XanoClient] = []

    def install(handler: Handler) -> None:
        def with_login(request: httpx.Request) -> httpx.Response:
            if request.url.path.endswith("/auth/login"):
                return httpx.Response(200, json={"authToken": "jwt-token"})
            if request.url.path.endswith("/brand"):
                return httpx.Response(200, json=[])
            return handler(request)

        def dependency() -> XanoClient:
            client = XanoClient(
                "https://tillin.test",
                email="svc@tillin.fr",
                password="secret",
                transport=httpx.MockTransport(with_login),
            )
            clients.append(client)
            return client

        app.dependency_overrides[get_xano_client] = dependency

    yield install
    app.dependency_overrides.pop(get_xano_client, None)
    for client in clients:
        client.close()


def _one_product(_: httpx.Request) -> httpx.Response:
    return httpx.Response(
        200,
        json={
            "items": [{"id": 101, "title": "Item", "brand_id": 7}],
            "itemsTotal": 1,
        },
    )


def test_requires_authentication(client: TestClient) -> None:
    response = client.get("/products", params={"search": "veste"})

    assert response.status_code == 401
    assert response.json()["code"] == "not_authenticated"


def test_search_products_maps_and_paginates(
    auth_client: TestClient, override_xano: InstallXano
) -> None:
    override_xano(_one_product)

    response = auth_client.get("/products", params={"search": "veste"})

    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 1
    assert body["total_pages"] == 1
    assert body["items"][0]["id"] == 101


def test_filters_are_forwarded_to_xano(
    auth_client: TestClient, override_xano: InstallXano
) -> None:
    captured: dict[str, httpx.Request] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["request"] = request
        return _one_product(request)

    override_xano(handler)

    response = auth_client.get(
        "/products", params={"search": "veste", "brand": 1332, "page": 2}
    )

    assert response.status_code == 200
    params = captured["request"].url.params
    assert params["search_query_text"] == "veste"
    assert params["search_query_brand"] == "1332"
    assert params["external[page]"] == "2"


def test_no_filters_is_allowed(
    auth_client: TestClient, override_xano: InstallXano
) -> None:
    override_xano(_one_product)

    response = auth_client.get("/products")

    assert response.status_code == 200
    assert response.json()["total"] == 1


def _detail_handler(detail: dict[str, Any] | None) -> Handler:
    """Handler for GET /product/{id}: detail body or upstream 404."""

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/get_all_informations"):
            return httpx.Response(200, json={"company_all_informations": {}})
        if "/product/" in request.url.path:
            if detail is None:
                return httpx.Response(404)
            return httpx.Response(200, json=detail)
        return httpx.Response(404)

    return handler


def test_get_product_requires_authentication(client: TestClient) -> None:
    assert client.get("/products/101").status_code == 401


def test_get_product_maps_detail(
    auth_client: TestClient, override_xano: InstallXano
) -> None:
    override_xano(
        _detail_handler(
            {
                "id": 101,
                "title": "Veste",
                "product_reference_code": "AW25-VM01",
                "product_variants": [
                    {"id": 1, "sku": "VM01-S", "price": {"amount": "89.90"}},
                    {"id": 2, "sku": "VM01-M"},
                ],
            }
        )
    )

    response = auth_client.get("/products/101")

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["id"] == 101
    assert body["reference_code"] == "AW25-VM01"
    # Nested `price.amount` mapped onto variant and product prices.
    assert Decimal(body["price"]) == Decimal("89.90")
    assert Decimal(body["variants"][0]["price"]) == Decimal("89.90")
    assert body["variants"][1]["price"] is None


def test_get_product_404_when_absent(
    auth_client: TestClient, override_xano: InstallXano
) -> None:
    override_xano(_detail_handler(None))

    response = auth_client.get("/products/9999")

    assert response.status_code == 404
    assert response.json()["code"] == "not_found"


def test_upstream_error_surfaces_as_502(
    auth_client: TestClient, override_xano: InstallXano
) -> None:
    override_xano(lambda request: httpx.Response(503))

    response = auth_client.get("/products", params={"search": "x"})

    assert response.status_code == 502
    assert response.json()["code"] == "xano_error"


def test_upload_product_images_forwards_multipart_and_maps_result(
    auth_client: TestClient, override_xano: InstallXano
) -> None:
    captured: dict[str, httpx.Request] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/bulk"):
            captured["request"] = request
            return httpx.Response(
                200,
                json={
                    "images": [
                        {"id": 5, "src": "https://xano.test/img-a.jpg", "position": 1},
                        {"id": 6, "src": "https://xano.test/img-b.png", "position": 2},
                    ]
                },
            )
        return httpx.Response(404)

    override_xano(handler)

    response = auth_client.post(
        "/products/101/images",
        files=[
            ("files", ("a.jpg", _image_bytes("JPEG"), "image/jpeg")),
            ("files", ("b.png", _image_bytes("PNG"), "image/png")),
        ],
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["created"] == 2
    assert [i["url"] for i in body["images"]] == [
        "https://xano.test/img-a.jpg",
        "https://xano.test/img-b.png",
    ]
    # The backend forwards to Tillin's bulk endpoint as multipart.
    request = captured["request"]
    assert request.url.path.endswith("/product_image/101/bulk")
    assert request.headers["content-type"].startswith("multipart/form-data")


def test_upload_product_images_surfaces_silent_tillin_rejection(
    auth_client: TestClient, override_xano: InstallXano
) -> None:
    # Tillin répond 200 avec images: [] quand il n'a rien créé : sans garde,
    # l'utilisateur recevait un « succès » à 0 image (vu en prod 2026-07-16).
    override_xano(
        lambda request: (
            httpx.Response(200, json={"images": []})
            if request.url.path.endswith("/bulk")
            else httpx.Response(404)
        )
    )

    response = auth_client.post(
        "/products/101/images",
        files=[("files", ("a.jpg", _image_bytes("JPEG"), "image/jpeg"))],
    )

    assert response.status_code == 502
    assert response.json()["code"] == "images_rejected"


def test_upload_product_images_rejects_a_non_image(
    auth_client: TestClient, override_xano: InstallXano
) -> None:
    override_xano(lambda request: httpx.Response(404))

    response = auth_client.post(
        "/products/101/images",
        files=[("files", ("notes.pdf", b"%PDF-1.4 nope", "application/pdf"))],
    )

    assert response.status_code == 422
    assert response.json()["code"] == "not_an_image"


def test_upload_product_images_rejects_empty(
    auth_client: TestClient, override_xano: InstallXano
) -> None:
    override_xano(lambda request: httpx.Response(404))
    # No files part at all -> FastAPI validation rejects the request.
    assert auth_client.post("/products/101/images").status_code == 422


def test_returns_503_when_xano_not_configured(
    auth_client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Authenticated, no override -> the real dependency runs. Force it
    # unconfigured (the dev .env may carry real creds) and reset the singleton
    # so no live call is made.
    from app.api import deps
    from app.core.config import settings

    monkeypatch.setattr(deps, "_xano_client", None)
    monkeypatch.setattr(settings, "XANO_BASE_URL", "")

    response = auth_client.get("/products", params={"search": "x"})

    assert response.status_code == 503
    assert response.json()["code"] == "xano_not_configured"
