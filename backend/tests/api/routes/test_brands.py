"""Tests for the brands routes (list + edit reference website URLs)."""

import json
from collections.abc import Callable, Iterator

import httpx
import pytest
from fastapi.testclient import TestClient

from app.api.deps import get_xano_client
from app.clients.xano import XanoClient
from app.main import app

Handler = Callable[[httpx.Request], httpx.Response]
InstallXano = Callable[[Handler], None]

BRANDS = [
    {"id": 2, "title": "Zeta", "brand_website": "zeta.com"},
    {"id": 1, "title": "Alpha", "website_urls": ["https://alpha.com"]},
]


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
    response = client.get("/brands")

    assert response.status_code == 401
    assert response.json()["code"] == "not_authenticated"


def test_list_brands_maps_and_sorts(
    auth_client: TestClient, override_xano: InstallXano
) -> None:
    override_xano(lambda request: httpx.Response(200, json=BRANDS))

    response = auth_client.get("/brands")

    assert response.status_code == 200
    assert response.json() == [
        {"id": 1, "name": "Alpha", "website_urls": ["https://alpha.com"]},
        {"id": 2, "name": "Zeta", "website_urls": ["https://zeta.com"]},
    ]


def test_list_brands_upstream_error_is_502(
    auth_client: TestClient, override_xano: InstallXano
) -> None:
    override_xano(lambda request: httpx.Response(503))

    response = auth_client.get("/brands")

    assert response.status_code == 502
    assert response.json()["code"] == "xano_error"


def test_update_website_urls_normalizes_and_posts(
    auth_client: TestClient, override_xano: InstallXano
) -> None:
    captured: dict[str, httpx.Request] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["request"] = request
        return httpx.Response(200, json={"ok": True})

    override_xano(handler)

    response = auth_client.put(
        "/brands/1332/website_urls",
        json={"website_urls": ["  gramicci.com  ", "//cdn.gramicci.jp", ""]},
    )

    assert response.status_code == 200
    assert response.json() == {
        "id": 1332,
        "name": None,
        "website_urls": ["https://gramicci.com", "https://cdn.gramicci.jp"],
    }
    request = captured["request"]
    assert request.method == "POST"
    assert request.url.path.endswith("/brand/1332/website_urls")
    assert json.loads(request.content) == {
        "brand_id": 1332,
        "website_urls": ["https://gramicci.com", "https://cdn.gramicci.jp"],
    }


def test_update_website_urls_validates_payload(
    auth_client: TestClient, override_xano: InstallXano
) -> None:
    override_xano(lambda request: httpx.Response(200, json={}))

    # Missing key
    assert auth_client.put("/brands/1/website_urls", json={}).status_code == 422
    # Not a list of strings
    assert (
        auth_client.put(
            "/brands/1/website_urls", json={"website_urls": [{"url": "x"}]}
        ).status_code
        == 422
    )
    # URL too long (> 500 chars)
    assert (
        auth_client.put(
            "/brands/1/website_urls", json={"website_urls": ["https://" + "a" * 500]}
        ).status_code
        == 422
    )
    # Too many URLs (> 20)
    assert (
        auth_client.put(
            "/brands/1/website_urls",
            json={"website_urls": [f"https://s{i}.com" for i in range(21)]},
        ).status_code
        == 422
    )


def test_update_website_urls_upstream_error_is_502(
    auth_client: TestClient, override_xano: InstallXano
) -> None:
    override_xano(lambda request: httpx.Response(500))

    response = auth_client.put(
        "/brands/1332/website_urls", json={"website_urls": ["https://a.com"]}
    )

    assert response.status_code == 502
    assert response.json()["code"] == "xano_error"


def test_update_website_urls_refreshes_every_client_brand_cache(
    auth_client: TestClient,
    override_xano: InstallXano,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Un site ajouté doit être vu par les jobs des AUTRES utilisateurs du
    # processus (chacun a son client Xano et sa carte des marques).
    import app.api.deps as deps
    from app.clients.xano import XanoClient

    other = XanoClient("https://tillin.test/api", token="other-user")
    other._brands = {1332: {"id": 1332, "title": "Gramicci"}}
    other._brands_expire_at = float("inf")
    monkeypatch.setattr(deps, "_token_clients", {"other-user": other})

    override_xano(lambda request: httpx.Response(200, json={}))
    response = auth_client.put(
        "/brands/1332/website_urls", json={"website_urls": ["gramicci.com"]}
    )
    assert response.status_code == 200
    assert other._brands is None
    other.close()
