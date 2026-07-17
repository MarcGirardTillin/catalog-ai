"""Tests for the best-effort page preview (og:image extraction)."""

import httpx

from app.sources.preview import fetch_page_preview

URL = "https://brand.example/products/bag-dark-bronze"


def _client(handler) -> httpx.Client:  # type: ignore[no-untyped-def]
    return httpx.Client(transport=httpx.MockTransport(handler))


def _html_response(html: str) -> httpx.Response:
    return httpx.Response(200, text=html, headers={"content-type": "text/html"})


def test_extracts_og_image() -> None:
    html = (
        "<html><head>"
        '<meta property="og:image" content="https://cdn.brand/img/bronze.jpg" />'
        "</head><body></body></html>"
    )
    with _client(lambda r: _html_response(html)) as client:
        assert (
            fetch_page_preview(URL, client=client) == "https://cdn.brand/img/bronze.jpg"
        )


def test_reversed_attribute_order_and_twitter_fallback() -> None:
    html = '<head><meta content="/img/relative.jpg" name="twitter:image" /></head>'
    with _client(lambda r: _html_response(html)) as client:
        # L'URL relative est résolue contre la page.
        assert (
            fetch_page_preview(URL, client=client)
            == "https://brand.example/img/relative.jpg"
        )


def test_non_html_or_error_returns_none() -> None:
    with _client(
        lambda r: httpx.Response(
            200, content=b"\x89PNG", headers={"content-type": "image/png"}
        )
    ) as client:
        assert fetch_page_preview(URL, client=client) is None
    with _client(lambda r: httpx.Response(404)) as client:
        assert fetch_page_preview(URL, client=client) is None

    def broken(_request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("boom")

    with _client(broken) as client:
        assert fetch_page_preview(URL, client=client) is None


def test_page_without_og_image_returns_none() -> None:
    with _client(lambda r: _html_response("<html><head></head></html>")) as client:
        assert fetch_page_preview(URL, client=client) is None
