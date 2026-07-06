"""Tests for GET /catalog/filters (auth + Xano dependency mocked)."""

from collections.abc import Callable, Iterator

import httpx
import pytest
from fastapi.testclient import TestClient

from app.api.deps import get_xano_client
from app.clients.xano import XanoClient
from app.main import app

Handler = Callable[[httpx.Request], httpx.Response]

COMPANY = {
    "brands": [{"id": 1, "title": "Alpha"}],
    "categories": [{"id": 5, "title": "Shoes", "parent_id": 0}],
    "seasons": [{"id": 8, "title": "SS25"}],
    "suppliers": [{"id": 3, "name": "ACME"}],
    "tags": [{"id": 7, "title": "New"}],
}


@pytest.fixture
def override_xano() -> Iterator[Callable[[Handler], None]]:
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
    assert client.get("/catalog/filters").status_code == 401


def test_filters_returns_classification(
    auth_client: TestClient, override_xano: Callable[[Handler], None]
) -> None:
    override_xano(
        lambda _: httpx.Response(200, json={"company_all_informations": COMPANY})
    )

    response = auth_client.get("/catalog/filters")

    assert response.status_code == 200
    body = response.json()
    assert body["brands"] == [{"id": 1, "title": "Alpha", "parent_id": None}]
    assert body["categories"][0]["parent_id"] == 0
    assert body["suppliers"][0]["title"] == "ACME"
