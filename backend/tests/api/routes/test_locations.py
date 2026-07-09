"""Tests for the locations route (import transfer destinations)."""

from collections.abc import Callable, Iterator

import httpx
import pytest
from fastapi.testclient import TestClient

from app.api.deps import get_xano_client
from app.clients.xano import XanoClient
from app.main import app

Handler = Callable[[httpx.Request], httpx.Response]
InstallXano = Callable[[Handler], None]

COMPANY = {
    "locations": [
        # `origin.third_party` non-empty = marketplace feed, excluded.
        {"id": 3, "title": "Zeta Store", "origin": {"third_party": ""}},
        {"id": 5, "title": "Marketplace", "origin": {"third_party": "shopify"}},
        {"id": 1, "title": "Alpha Shop"},
    ]
}


@pytest.fixture
def override_xano() -> Iterator[InstallXano]:
    """Install a Xano client backed by a MockTransport for the dependency."""
    clients: list[XanoClient] = []

    def install(handler: Handler) -> None:
        def with_login(request: httpx.Request) -> httpx.Response:
            if request.url.path.endswith("/auth/login"):
                return httpx.Response(200, json={"authToken": "jwt-token"})
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


def test_requires_authentication(client: TestClient) -> None:
    response = client.get("/locations")

    assert response.status_code == 401
    assert response.json()["code"] == "not_authenticated"


def test_list_locations_filters_and_sorts(
    auth_client: TestClient, override_xano: InstallXano
) -> None:
    override_xano(
        lambda request: httpx.Response(200, json={"company_all_informations": COMPANY})
    )

    response = auth_client.get("/locations")

    assert response.status_code == 200
    assert response.json() == [
        {"id": 1, "title": "Alpha Shop"},
        {"id": 3, "title": "Zeta Store"},
    ]


def test_list_locations_upstream_error_is_502(
    auth_client: TestClient, override_xano: InstallXano
) -> None:
    override_xano(lambda request: httpx.Response(500))

    response = auth_client.get("/locations")

    assert response.status_code == 502
    assert response.json()["code"] == "xano_error"
