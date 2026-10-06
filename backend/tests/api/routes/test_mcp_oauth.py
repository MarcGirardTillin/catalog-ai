"""Parcours OAuth 2.1 du serveur MCP, de bout en bout en HTTP (comme
claude.ai) : métadonnées, DCR, /authorize → consentement, /token (PKCE),
appel /mcp, rotation, refus, scopes."""

import base64
import hashlib
import secrets
from typing import Any
from urllib.parse import parse_qs, urlparse

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session, sessionmaker

import app.mcp.auth as mcp_auth
import app.mcp.guard as mcp_guard
import app.mcp.oauth as mcp_oauth
from app.core.config import settings

REDIRECT = "https://claude.ai/api/mcp/auth_callback"
MCP_HEADERS = {
    "Accept": "application/json, text/event-stream",
    "Content-Type": "application/json",
}


@pytest.fixture(autouse=True)
def _oauth_sessions(
    db_session_factory: sessionmaker[Session], monkeypatch: pytest.MonkeyPatch
) -> None:
    for module in (mcp_oauth, mcp_guard, mcp_auth):
        monkeypatch.setattr(module, "SessionLocal", db_session_factory)


def _pkce() -> tuple[str, str]:
    verifier = secrets.token_urlsafe(48)
    digest = hashlib.sha256(verifier.encode()).digest()
    return verifier, base64.urlsafe_b64encode(digest).rstrip(b"=").decode()


def _register(client: TestClient) -> str:
    response = client.post(
        "/register",
        json={
            "client_name": "Claude",
            "redirect_uris": [REDIRECT],
            "token_endpoint_auth_method": "none",
            "grant_types": ["authorization_code", "refresh_token"],
            "response_types": ["code"],
        },
    )
    assert response.status_code == 201, response.text
    client_id: str = response.json()["client_id"]
    return client_id


def _authorize(client: TestClient, client_id: str, challenge: str, scope: str) -> str:
    """Renvoie la clé de la demande de consentement."""
    response = client.get(
        "/authorize",
        params={
            "response_type": "code",
            "client_id": client_id,
            "redirect_uri": REDIRECT,
            "code_challenge": challenge,
            "code_challenge_method": "S256",
            "state": "etat-123",
            "scope": scope,
        },
        follow_redirects=False,
    )
    assert response.status_code in (302, 307), response.text
    location = response.headers["location"]
    assert location.startswith(f"{settings.PUBLIC_APP_URL}/oauth/consent?request=")
    return parse_qs(urlparse(location).query)["request"][0]


def _connect(
    auth_client: TestClient, scope: str = "catalogai:read catalogai:write"
) -> dict[str, Any]:
    client_id = _register(auth_client)
    verifier, challenge = _pkce()
    key = _authorize(auth_client, client_id, challenge, scope)

    request = auth_client.get(f"/oauth/requests/{key}")
    assert request.status_code == 200
    assert request.json()["client_name"] == "Claude"
    assert request.json()["redirect_host"] == "claude.ai"

    approved = auth_client.post(f"/oauth/requests/{key}/approve")
    assert approved.status_code == 200
    redirect = urlparse(approved.json()["redirect_url"])
    query = parse_qs(redirect.query)
    assert f"{redirect.scheme}://{redirect.netloc}{redirect.path}" == REDIRECT
    assert query["state"] == ["etat-123"]

    token = auth_client.post(
        "/token",
        data={
            "grant_type": "authorization_code",
            "code": query["code"][0],
            "redirect_uri": REDIRECT,
            "client_id": client_id,
            "code_verifier": verifier,
        },
    )
    assert token.status_code == 200, token.text
    return {"client_id": client_id, "code": query["code"][0], **token.json()}


def _tools_call(
    client: TestClient, access_token: str, name: str, args: dict[str, Any]
) -> Any:
    return client.post(
        "/mcp",
        headers={**MCP_HEADERS, "Authorization": f"Bearer {access_token}"},
        json={
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {"name": name, "arguments": args},
        },
    )


def test_discovery_metadata(client: TestClient) -> None:
    resource = client.get("/.well-known/oauth-protected-resource/mcp")
    assert resource.status_code == 200, resource.text
    body = resource.json()
    assert body["resource"].endswith("/mcp")
    assert body["authorization_servers"]
    server = client.get("/.well-known/oauth-authorization-server")
    assert server.status_code == 200
    meta = server.json()
    assert meta["authorization_endpoint"].endswith("/authorize")
    assert meta["token_endpoint"].endswith("/token")
    assert meta["registration_endpoint"].endswith("/register")
    assert "S256" in meta["code_challenge_methods_supported"]
    # Sans jeton, le 401 pointe vers les métadonnées de la ressource.
    unauthenticated = client.post(
        "/mcp",
        headers=MCP_HEADERS,
        json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"},
    )
    assert unauthenticated.status_code == 401
    assert "resource_metadata" in unauthenticated.headers["www-authenticate"]


def test_full_oauth_flow_then_mcp_call_and_refresh_rotation(
    auth_client: TestClient,
) -> None:
    tokens = _connect(auth_client)
    assert tokens["token_type"].lower() == "bearer"
    assert set(tokens["scope"].split()) == {"catalogai:read", "catalogai:write"}

    listed = auth_client.post(
        "/mcp",
        headers={**MCP_HEADERS, "Authorization": f"Bearer {tokens['access_token']}"},
        json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"},
    )
    assert listed.status_code == 200, listed.text
    overview = _tools_call(
        auth_client, tokens["access_token"], "catalogai_get_account_overview", {}
    )
    assert overview.status_code == 200
    assert overview.json()["result"]["isError"] is False

    # Le code ne s'échange qu'une fois.
    reused = auth_client.post(
        "/token",
        data={
            "grant_type": "authorization_code",
            "code": tokens["code"],
            "redirect_uri": REDIRECT,
            "client_id": tokens["client_id"],
            "code_verifier": "x" * 50,
        },
    )
    assert reused.status_code in (400, 401)

    # Rotation : nouveau couple, l'ancien jeton d'accès ne passe plus.
    refreshed = auth_client.post(
        "/token",
        data={
            "grant_type": "refresh_token",
            "refresh_token": tokens["refresh_token"],
            "client_id": tokens["client_id"],
        },
    )
    assert refreshed.status_code == 200, refreshed.text
    new_tokens = refreshed.json()
    old = _tools_call(auth_client, tokens["access_token"], "catalogai_list_brands", {})
    assert old.status_code == 401
    again = auth_client.post(
        "/token",
        data={
            "grant_type": "refresh_token",
            "refresh_token": tokens["refresh_token"],
            "client_id": tokens["client_id"],
        },
    )
    assert again.status_code in (400, 401)
    ok = _tools_call(
        auth_client, new_tokens["access_token"], "catalogai_get_account_overview", {}
    )
    assert ok.status_code == 200


def test_read_only_grant_cannot_write(auth_client: TestClient) -> None:
    tokens = _connect(auth_client, scope="catalogai:read")
    response = _tools_call(
        auth_client,
        tokens["access_token"],
        "catalogai_start_enrichment",
        {"product_ids": [1]},
    )
    assert response.status_code == 200
    result = response.json()["result"]
    assert result["isError"] is True
    assert "lecture seule" in result["content"][0]["text"]


def test_user_can_deny_and_consent_requires_session(
    client: TestClient, auth_client: TestClient
) -> None:
    client_id = _register(auth_client)
    _, challenge = _pkce()
    key = _authorize(auth_client, client_id, challenge, "catalogai:read")

    denied = auth_client.post(f"/oauth/requests/{key}/deny")
    assert denied.status_code == 200
    query = parse_qs(urlparse(denied.json()["redirect_url"]).query)
    assert query["error"] == ["access_denied"]
    assert query["state"] == ["etat-123"]
    # Une demande traitée ne se rouvre pas.
    assert auth_client.get(f"/oauth/requests/{key}").status_code == 404

    key2 = _authorize(auth_client, client_id, challenge, "catalogai:read")
    auth_client.post("/auth/logout")
    assert client.get(f"/oauth/requests/{key2}").status_code == 401
    assert client.post(f"/oauth/requests/{key2}/approve").status_code == 401


def test_personal_token_still_works_alongside_oauth(auth_client: TestClient) -> None:
    secret = auth_client.post("/api-tokens", json={"name": "Codex"}).json()["secret"]
    response = _tools_call(auth_client, secret, "catalogai_get_account_overview", {})
    assert response.status_code == 200
    assert response.json()["result"]["isError"] is False
