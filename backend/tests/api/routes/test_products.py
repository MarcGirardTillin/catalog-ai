"""Tests for the GET /products read path (auth + Xano dependency mocked)."""

from collections.abc import Callable, Generator, Iterator

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
        def dependency() -> Generator[XanoClient]:
            client = XanoClient(
                base_url="https://tillin.test",
                token="t",
                transport=httpx.MockTransport(handler),
            )
            clients.append(client)
            try:
                yield client
            finally:
                client.close()

        app.dependency_overrides[get_xano_client] = dependency

    yield install
    app.dependency_overrides.pop(get_xano_client, None)
    for client in clients:
        client.close()


def _ok_handler(_: httpx.Request) -> httpx.Response:
    return httpx.Response(
        200,
        json={"items": [{"id": 101, "name": "Item"}], "itemsTotal": 1},
    )


def test_requires_authentication(client: TestClient) -> None:
    response = client.get("/products", params={"tag": "ss25"})

    assert response.status_code == 401
    assert response.json()["code"] == "not_authenticated"


def test_list_products_by_tag(
    auth_client: TestClient, override_xano: InstallXano
) -> None:
    override_xano(_ok_handler)

    response = auth_client.get("/products", params={"tag": "ss25"})

    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 1
    assert body["total_pages"] == 1
    assert body["items"][0]["id"] == 101


def test_list_products_by_ids(
    auth_client: TestClient, override_xano: InstallXano
) -> None:
    captured: dict[str, httpx.Request] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["request"] = request
        return _ok_handler(request)

    override_xano(handler)

    response = auth_client.get("/products", params=[("ids", 101), ("ids", 102)])

    assert response.status_code == 200
    assert captured["request"].url.params["ids"] == "101,102"


def test_requires_exactly_one_selector(
    auth_client: TestClient, override_xano: InstallXano
) -> None:
    override_xano(_ok_handler)

    neither = auth_client.get("/products")
    both = auth_client.get("/products", params={"tag": "ss25", "ids": 1})

    assert neither.status_code == 400
    assert neither.json()["code"] == "invalid_selection"
    assert both.status_code == 400


def test_upstream_error_surfaces_as_502(
    auth_client: TestClient, override_xano: InstallXano
) -> None:
    override_xano(lambda request: httpx.Response(503))

    response = auth_client.get("/products", params={"tag": "ss25"})

    assert response.status_code == 502
    assert response.json()["code"] == "xano_error"


def test_returns_503_when_xano_not_configured(auth_client: TestClient) -> None:
    # Authenticated, but no Xano override -> the real dependency runs with empty
    # settings.
    response = auth_client.get("/products", params={"tag": "ss25"})

    assert response.status_code == 503
    assert response.json()["code"] == "xano_not_configured"
