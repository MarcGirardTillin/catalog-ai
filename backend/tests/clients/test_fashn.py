"""Unit tests for the FASHN client (all transports mocked)."""

import json
from collections.abc import Callable

import httpx
import pytest

from app.clients.base import ExternalServiceError, NotConfiguredError
from app.clients.fashn import FashnClient


def _client(handler: Callable[[httpx.Request], httpx.Response]) -> FashnClient:
    return FashnClient("fx-key", transport=httpx.MockTransport(handler))


def test_run_posts_model_and_inputs_and_returns_prediction_id() -> None:
    captured: dict[str, httpx.Request] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["request"] = request
        return httpx.Response(200, json={"id": "pred-123", "status": "starting"})

    with _client(handler) as client:
        prediction_id = client.run(
            "product-to-model", {"product_image": "https://img/1.jpg", "seed": 42}
        )

    assert prediction_id == "pred-123"
    request = captured["request"]
    assert request.url.path == "/v1/run"
    assert request.headers["Authorization"] == "Bearer fx-key"
    body = json.loads(request.content)
    assert body["model_name"] == "product-to-model"
    assert body["inputs"]["product_image"] == "https://img/1.jpg"


def test_wait_polls_until_completed_and_returns_output_urls() -> None:
    calls = {"status": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v1/status/pred-123"
        calls["status"] += 1
        if calls["status"] < 3:
            return httpx.Response(200, json={"id": "pred-123", "status": "processing"})
        return httpx.Response(
            200,
            json={
                "id": "pred-123",
                "status": "completed",
                "output": ["https://cdn.fashn.ai/a.jpg", "https://cdn.fashn.ai/b.jpg"],
            },
        )

    with _client(handler) as client:
        urls = client.wait("pred-123", timeout=5.0, poll_interval=0.0)

    assert calls["status"] == 3
    assert urls == ["https://cdn.fashn.ai/a.jpg", "https://cdn.fashn.ai/b.jpg"]


def test_wait_failed_raises_with_upstream_error() -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200, json={"id": "p", "status": "failed", "error": "NSFW input"}
        )

    with _client(handler) as client:
        with pytest.raises(ExternalServiceError) as excinfo:
            client.wait("p", poll_interval=0.0)

    assert excinfo.value.detail == {"error": "NSFW input"}


def test_wait_timeout_raises() -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"id": "p", "status": "in_queue"})

    with _client(handler) as client:
        with pytest.raises(ExternalServiceError) as excinfo:
            client.wait("p", timeout=0.0, poll_interval=0.0)

    assert "timed out" in excinfo.value.message


def test_wait_unexpected_status_raises() -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"id": "p", "status": "canceled"})

    with _client(handler) as client:
        with pytest.raises(ExternalServiceError):
            client.wait("p", poll_interval=0.0)


def test_download_returns_bytes() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url == "https://cdn.fashn.ai/a.jpg"
        return httpx.Response(200, content=b"\xff\xd8jpeg-bytes")

    with _client(handler) as client:
        data = client.download("https://cdn.fashn.ai/a.jpg")

    assert data == b"\xff\xd8jpeg-bytes"


def test_upstream_errors_raise() -> None:
    with _client(lambda r: httpx.Response(500)) as client:
        with pytest.raises(ExternalServiceError):
            client.run("product-to-model", {})
        with pytest.raises(ExternalServiceError):
            client.wait("p", poll_interval=0.0)
        with pytest.raises(ExternalServiceError):
            client.download("https://cdn.fashn.ai/a.jpg")


def test_requires_api_key() -> None:
    with pytest.raises(NotConfiguredError):
        FashnClient("")
