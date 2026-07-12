"""Tests for the external service clients (all transports mocked)."""

import json

import anthropic
import httpx
import pytest

from app.clients.base import ExternalServiceError, NotConfiguredError
from app.clients.brevo import BrevoClient
from app.clients.claude import ClaudeClient
from app.clients.firecrawl import FirecrawlClient
from app.clients.photoroom import PhotoroomClient

# ---- Claude ----


def _claude_response(payload: dict[str, object]) -> dict[str, object]:
    return {
        "id": "msg_test",
        "type": "message",
        "role": "assistant",
        "model": "claude-sonnet-5",
        "content": [{"type": "text", "text": json.dumps(payload)}],
        "stop_reason": "end_turn",
        "stop_sequence": None,
        "usage": {"input_tokens": 10, "output_tokens": 20},
    }


def _claude_client(handler) -> ClaudeClient:  # type: ignore[no-untyped-def]
    return ClaudeClient(
        "sk-test",
        http_client=anthropic.DefaultHttpxClient(
            transport=httpx.MockTransport(handler)
        ),
    )


def test_claude_generate_copy_parses_structured_output() -> None:
    captured: dict[str, httpx.Request] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["request"] = request
        return httpx.Response(
            200,
            json=_claude_response(
                {
                    "description_fr": "Un short robuste et léger.",
                    "meta_description_fr": "Short Gramicci en coton.",
                }
            ),
        )

    result = _claude_client(handler).generate_copy(
        {"title": "G-Short", "brand": "Gramicci"},
        editorial_instructions="Ton sobre.",
    )

    assert result.description_fr.startswith("Un short")
    request = captured["request"]
    assert request.url.path == "/v1/messages"
    assert request.headers["x-api-key"] == "sk-test"
    assert request.headers["anthropic-version"]
    body = json.loads(request.content)
    assert body["model"] == "claude-sonnet-5"
    assert body["output_config"]["format"]["type"] == "json_schema"
    # Sonnet 5 rejects sampling params — none must be sent.
    assert "temperature" not in body
    assert "Ton sobre." in body["messages"][0]["content"]


def test_claude_meta_max_length_parameterizes_system_prompt() -> None:
    captured: dict[str, httpx.Request] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["request"] = request
        return httpx.Response(
            200,
            json=_claude_response(
                {"description_fr": "Desc.", "meta_description_fr": "Meta."}
            ),
        )

    client = _claude_client(handler)
    client.generate_copy({"title": "G-Short"}, meta_max_length=140)
    body = json.loads(captured["request"].content)
    assert "140 caractères maximum" in body["system"]

    # The default stays at 160 characters.
    client.generate_copy({"title": "G-Short"})
    body = json.loads(captured["request"].content)
    assert "160 caractères maximum" in body["system"]


def test_claude_refusal_and_upstream_error_raise() -> None:
    def refusal(_: httpx.Request) -> httpx.Response:
        payload = _claude_response({})
        payload["stop_reason"] = "refusal"
        payload["content"] = []
        return httpx.Response(200, json=payload)

    with pytest.raises(ExternalServiceError):
        _claude_client(refusal).generate_copy({"title": "X"})

    def error(_: httpx.Request) -> httpx.Response:
        return httpx.Response(
            500,
            json={"type": "error", "error": {"type": "api_error", "message": "boom"}},
        )

    with pytest.raises(ExternalServiceError):
        _claude_client(error).generate_copy({"title": "X"})


def test_claude_requires_api_key() -> None:
    with pytest.raises(NotConfiguredError):
        ClaudeClient("")


# ---- Photoroom ----


def test_photoroom_remove_background_posts_multipart_to_sdk_host() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        # Confirmed live (2026-07-12): multipart POST on the sdk host.
        assert request.method == "POST"
        assert request.url.host == "sdk.photoroom.com"
        assert request.url.path == "/v1/segment"
        assert request.headers["x-api-key"] == "pr-key"
        assert b"image_file" in request.content
        return httpx.Response(200, content=b"\x89PNG-rgba")

    with PhotoroomClient("pr-key", transport=httpx.MockTransport(handler)) as client:
        assert client.remove_background(b"source-bytes") == b"\x89PNG-rgba"


def test_photoroom_error_raises() -> None:
    with PhotoroomClient(
        "pr-key", transport=httpx.MockTransport(lambda r: httpx.Response(402))
    ) as client:
        with pytest.raises(ExternalServiceError):
            client.remove_background(b"source-bytes")
    with pytest.raises(NotConfiguredError):
        PhotoroomClient("")


# ---- Firecrawl ----


def test_firecrawl_scrape_returns_data() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["Authorization"] == "Bearer fc-key"
        assert json.loads(request.content)["url"] == "https://brand.example/p/1"
        return httpx.Response(
            200, json={"success": True, "data": {"markdown": "# Produit"}}
        )

    with FirecrawlClient("fc-key", transport=httpx.MockTransport(handler)) as client:
        data = client.scrape("https://brand.example/p/1")

    assert data["markdown"] == "# Produit"


def test_firecrawl_search_posts_query_and_returns_web_hits() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v2/search"
        assert request.headers["Authorization"] == "Bearer fc-key"
        body = json.loads(request.content)
        assert body == {
            "query": "site:brand.example G5FU-T081",
            "limit": 5,
            "sources": ["web"],
        }
        return httpx.Response(
            200,
            json={
                "success": True,
                "data": {
                    "web": [
                        {
                            "url": "https://brand.example/p/1",
                            "title": "G-Short",
                            "description": "Le short.",
                            "position": 1,
                        }
                    ]
                },
            },
        )

    with FirecrawlClient("fc-key", transport=httpx.MockTransport(handler)) as client:
        hits = client.search("site:brand.example G5FU-T081")

    assert hits == [
        {
            "url": "https://brand.example/p/1",
            "title": "G-Short",
            "description": "Le short.",
            "position": 1,
        }
    ]


def test_firecrawl_search_empty_and_error() -> None:
    with FirecrawlClient(
        "fc-key",
        transport=httpx.MockTransport(
            lambda r: httpx.Response(200, json={"success": True, "data": {}})
        ),
    ) as client:
        assert client.search("site:x.example nothing") == []

    with FirecrawlClient(
        "fc-key", transport=httpx.MockTransport(lambda r: httpx.Response(500))
    ) as client:
        with pytest.raises(ExternalServiceError):
            client.search("boom")


def test_firecrawl_extract_product_uses_json_format() -> None:
    extracted = {
        "title": "G-Short Double Navy",
        "description": "Le short d'origine.",
        "images": ["https://brand.example/img/1.jpg"],
        "reference_codes": ["G5FU-T081"],
    }

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v2/scrape"
        body = json.loads(request.content)
        assert body["url"] == "https://brand.example/p/1"
        (fmt,) = body["formats"]
        assert fmt["type"] == "json"
        assert fmt["schema"]["required"] == ["title"]
        assert "reference_codes" in fmt["schema"]["properties"]
        assert fmt["prompt"]
        return httpx.Response(200, json={"success": True, "data": {"json": extracted}})

    with FirecrawlClient("fc-key", transport=httpx.MockTransport(handler)) as client:
        assert client.extract_product("https://brand.example/p/1") == extracted


def test_firecrawl_extract_product_none_when_json_absent() -> None:
    with FirecrawlClient(
        "fc-key",
        transport=httpx.MockTransport(
            lambda r: httpx.Response(
                200, json={"success": True, "data": {"metadata": {}}}
            )
        ),
    ) as client:
        assert client.extract_product("https://brand.example/p/1") is None

    with FirecrawlClient(
        "fc-key", transport=httpx.MockTransport(lambda r: httpx.Response(429))
    ) as client:
        with pytest.raises(ExternalServiceError):
            client.extract_product("https://brand.example/p/1")


def test_firecrawl_requires_key() -> None:
    with pytest.raises(NotConfiguredError):
        FirecrawlClient("")


# ---- Brevo ----


def test_brevo_send_email() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v3/smtp/email"
        assert request.headers["api-key"] == "bv-key"
        body = json.loads(request.content)
        assert body["sender"]["email"] == "noreply@catalogai.io"
        assert body["to"] == [{"email": "marc@tillin.fr"}]
        return httpx.Response(201, json={"messageId": "<msg-1@brevo>"})

    with BrevoClient(
        "bv-key",
        sender_email="noreply@catalogai.io",
        transport=httpx.MockTransport(handler),
    ) as client:
        message_id = client.send_email(
            to="marc@tillin.fr", subject="Job terminé", html="<p>OK</p>"
        )

    assert message_id == "<msg-1@brevo>"


def test_brevo_requires_key_and_sender() -> None:
    with pytest.raises(NotConfiguredError):
        BrevoClient("", sender_email="x@y.fr")
    with pytest.raises(NotConfiguredError):
        BrevoClient("bv-key", sender_email="")
