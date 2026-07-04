"""Tests for the authentication routes and session cookie."""

from typing import Any

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
