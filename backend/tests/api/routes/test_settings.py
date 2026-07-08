"""Tests for user preferences, account settings, and password change."""

from typing import Any

from fastapi.testclient import TestClient

from tests.conftest import TEST_USER_PASSWORD


def test_settings_require_authentication(client: TestClient) -> None:
    assert client.get("/settings/me").status_code == 401
    assert client.get("/settings/account").status_code == 401
    assert client.get("/settings/connection").status_code == 401


def test_user_preferences_defaults_and_roundtrip(auth_client: TestClient) -> None:
    body = auth_client.get("/settings/me").json()
    # Shortcuts are opt-in.
    assert body == {
        "shortcuts_enabled": False,
        "auto_advance": True,
        "density": "comfortable",
        "products_per_page": 20,
    }

    updated = auth_client.put(
        "/settings/me",
        json={
            "shortcuts_enabled": True,
            "auto_advance": False,
            "density": "compact",
            "products_per_page": 50,
        },
    )
    assert updated.status_code == 200
    assert auth_client.get("/settings/me").json()["shortcuts_enabled"] is True

    # Invalid values are rejected.
    assert (
        auth_client.put(
            "/settings/me",
            json={"density": "cosy"},
        ).status_code
        == 422
    )


def test_account_settings_roundtrip_and_job_defaults(auth_client: TestClient) -> None:
    payload: dict[str, Any] = {
        "title_template": "{title} {color}",
        "editorial_instructions": "Ton chaleureux, vouvoiement.",
        "client_context": "# Boutique\nMode responsable à Lyon.",
        "meta_max_length": 155,
        "notify_on_job_done": True,
        "notify_email": "shop@example.com",
    }
    assert auth_client.put("/settings/account", json=payload).status_code == 200
    assert auth_client.get("/settings/account").json() == payload

    # New jobs inherit the account defaults…
    job = auth_client.post("/jobs", json={"selection": {"ids": [1]}}).json()
    assert job["config_json"]["title_template"] == "{title} {color}"
    assert (
        job["config_json"]["editorial_instructions"] == "Ton chaleureux, vouvoiement."
    )
    assert (
        job["config_json"]["client_context"] == "# Boutique\nMode responsable à Lyon."
    )
    assert job["config_json"]["meta_max_length"] == 155

    # …unless the job explicitly overrides them.
    override = auth_client.post(
        "/jobs",
        json={"selection": {"ids": [2]}, "config": {"title_template": "{title}"}},
    ).json()
    assert override["config_json"]["title_template"] == "{title}"


def test_connection_status_reports_unconfigured(auth_client: TestClient) -> None:
    # The autouse fixture blanks XANO_BASE_URL, so Xano reads as unconfigured.
    body = auth_client.get("/settings/connection").json()
    assert body == {"configured": False, "host": None, "data_source": None}


def test_password_change_flow(auth_client: TestClient) -> None:
    wrong = auth_client.post(
        "/auth/password",
        json={"current_password": "not-the-password", "new_password": "new-password-1"},
    )
    assert wrong.status_code == 400

    too_short = auth_client.post(
        "/auth/password",
        json={"current_password": TEST_USER_PASSWORD, "new_password": "short"},
    )
    assert too_short.status_code == 422

    ok = auth_client.post(
        "/auth/password",
        json={"current_password": TEST_USER_PASSWORD, "new_password": "new-password-1"},
    )
    assert ok.status_code == 204

    # The old password no longer works; the new one does.
    assert (
        auth_client.post(
            "/auth/login",
            json={"email": "dev@catalogai.io", "password": TEST_USER_PASSWORD},
        ).status_code
        == 401
    )
    assert (
        auth_client.post(
            "/auth/login",
            json={"email": "dev@catalogai.io", "password": "new-password-1"},
        ).status_code
        == 200
    )
