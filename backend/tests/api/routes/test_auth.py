"""Tests for the authentication routes and session cookie."""

from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.core.config import settings


def test_login_sets_cookie_and_returns_user(
    client: TestClient, test_user: dict[str, Any]
) -> None:
    response = client.post(
        "/auth/login",
        json={"email": test_user["email"], "password": test_user["password"]},
    )

    assert response.status_code == 200
    assert response.json()["email"] == test_user["email"]
    assert settings.AUTH_COOKIE_NAME in response.cookies


def test_login_with_wrong_password_is_401(
    client: TestClient, test_user: dict[str, Any]
) -> None:
    response = client.post(
        "/auth/login",
        json={"email": test_user["email"], "password": "wrong"},
    )

    assert response.status_code == 401
    assert response.json()["code"] == "invalid_credentials"


def _enable_xano(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "XANO_BASE_URL", "https://tillin.test/api")
    monkeypatch.setattr(settings, "XANO_LOGIN_EMAIL", "svc@tillin.fr")
    monkeypatch.setattr(settings, "XANO_LOGIN_PASSWORD", "secret")


def test_login_falls_back_to_xano_and_creates_user(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    _enable_xano(monkeypatch)
    monkeypatch.setattr(
        "app.api.routes.auth.verify_login",
        lambda *a, **k: {"email": "buyer@tillin.fr", "full_name": "Buyer"},
    )

    response = client.post(
        "/auth/login", json={"email": "buyer@tillin.fr", "password": "xano-pw"}
    )

    assert response.status_code == 200
    assert response.json()["email"] == "buyer@tillin.fr"
    assert response.json()["full_name"] == "Buyer"
    assert settings.AUTH_COOKIE_NAME in response.cookies
    # The federated user is now a local user and can be resolved by the cookie.
    assert client.get("/auth/me").json()["email"] == "buyer@tillin.fr"


def test_login_rejects_when_xano_also_fails(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    _enable_xano(monkeypatch)
    monkeypatch.setattr("app.api.routes.auth.verify_login", lambda *a, **k: None)

    response = client.post(
        "/auth/login", json={"email": "nobody@tillin.fr", "password": "nope"}
    )

    assert response.status_code == 401
    assert response.json()["code"] == "invalid_credentials"


def test_me_requires_authentication(client: TestClient) -> None:
    response = client.get("/auth/me")

    assert response.status_code == 401
    assert response.json()["code"] == "not_authenticated"


def test_me_returns_current_user_when_logged_in(
    auth_client: TestClient, test_user: dict[str, Any]
) -> None:
    response = auth_client.get("/auth/me")

    assert response.status_code == 200
    assert response.json()["id"] == test_user["id"]


def test_logout_clears_session(
    auth_client: TestClient,
) -> None:
    assert auth_client.get("/auth/me").status_code == 200

    logout = auth_client.post("/auth/logout")
    assert logout.status_code == 204

    assert auth_client.get("/auth/me").status_code == 401


def test_invalid_cookie_is_rejected(client: TestClient) -> None:
    client.cookies.set(settings.AUTH_COOKIE_NAME, "not-a-jwt")

    response = client.get("/auth/me")

    assert response.status_code == 401
