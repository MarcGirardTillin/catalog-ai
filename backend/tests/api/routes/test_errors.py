import pytest
from fastapi.testclient import TestClient

from app.api.exceptions import AppException
from app.api.routes import system


def test_validation_error_uses_standard_shape(client: TestClient) -> None:
    response = client.get(
        "/example",
        params={"sample_id": "invalid"},
    )
    assert response.status_code == 422

    payload = response.json()
    assert payload["code"] == "validation_error"
    assert payload["message"] == "Request validation failed"
    assert isinstance(payload["detail"], list)
    assert len(payload["detail"]) >= 1


def test_http_exception_uses_standard_shape(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(system, "ping_database", lambda: False)
    response = client.get("/healthcheck")
    assert response.status_code == 503
    assert response.json() == {
        "code": "http_error",
        "message": "Database unavailable",
        "detail": "Database unavailable",
    }


def test_app_exception_uses_standard_shape(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    def raise_app_exception() -> bool:
        raise AppException(
            status_code=503,
            code="database_unavailable",
            message="Database unavailable",
            detail={"component": "database"},
        )

    monkeypatch.setattr(system, "ping_database", raise_app_exception)
    response = client.get("/healthcheck")
    assert response.status_code == 503
    assert response.json() == {
        "code": "database_unavailable",
        "message": "Database unavailable",
        "detail": {"component": "database"},
    }


def test_unhandled_exception_uses_standard_shape(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    def raise_runtime_error() -> bool:
        raise RuntimeError("boom")

    monkeypatch.setattr(system, "ping_database", raise_runtime_error)
    with TestClient(client.app, raise_server_exceptions=False) as safe_client:
        response = safe_client.get("/healthcheck")
    assert response.status_code == 500
    assert response.json() == {
        "code": "internal_server_error",
        "message": "Internal server error",
        "detail": None,
    }
