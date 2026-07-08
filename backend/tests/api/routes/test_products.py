"""Tests for the GET /products search path (auth + Xano dependency mocked)."""

from collections.abc import Callable, Iterator

import httpx
import pytest
from fastapi.testclient import TestClient

from app.api.deps import get_xano_client
from app.clients.xano import XanoClient
from app.main import app

Handler = Callable[[httpx.Request], httpx.Response]
InstallXano = Callable[[Handler], None]


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


def test_upstream_error_surfaces_as_502(
    auth_client: TestClient, override_xano: InstallXano
) -> None:
    override_xano(lambda request: httpx.Response(503))

    response = auth_client.get("/products", params={"search": "x"})

    assert response.status_code == 502
    assert response.json()["code"] == "xano_error"


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
