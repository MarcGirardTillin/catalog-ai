import pytest
from fastapi.testclient import TestClient

import app.api.routes.system as system
import app.main as main_module
from app.core.config import settings


def test_healthcheck_returns_200(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(system, "ping_database", lambda: True)
    response = client.get("/healthcheck")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "database": "up"}


def test_version_returns_app_and_version(client: TestClient) -> None:
    response = client.get("/version")
    assert response.status_code == 200

    payload = response.json()
    assert payload["app"]
    assert payload["version"]
    assert payload["environment"] == "local"
    assert payload["build"] is None
    assert payload["commit"] is None
    assert payload["branch"] is None


def test_version_exposes_build_metadata(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "APP_VERSION", "1.2.3")
    monkeypatch.setattr(settings, "APP_BUILD", "main-42")
    monkeypatch.setattr(settings, "APP_COMMIT_SHA", "abcdef1")
    monkeypatch.setattr(settings, "APP_BRANCH", "main")
    monkeypatch.setattr(settings, "ENVIRONMENT", "production")

    response = client.get("/version")

    assert response.status_code == 200
    assert response.json() == {
        "app": settings.PROJECT_NAME,
        "version": "1.2.3",
        "build": "main-42",
        "commit": "abcdef1",
        "branch": "main",
        "environment": "production",
    }


def test_system_endpoints_stay_public(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(system, "ping_database", lambda: True)
    version_response = client.get("/version")
    health_response = client.get("/healthcheck")

    assert version_response.status_code == 200
    assert health_response.status_code == 200


def test_cors_preflight_allows_local_frontend_origin(client: TestClient) -> None:
    response = client.options(
        "/example",
        headers={
            "Access-Control-Request-Method": "GET",
            "Origin": "http://localhost:5173",
        },
    )

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "http://localhost:5173"
    assert "GET" in response.headers["access-control-allow-methods"]


def test_app_startup_fails_when_database_is_unreachable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(main_module, "ping_database", lambda: False)

    with pytest.raises(RuntimeError, match="PostgreSQL is not reachable at startup"):
        with TestClient(main_module.app):
            pass
