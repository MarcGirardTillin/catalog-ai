"""Repli « empreinte navigateur » sur défi Cloudflare (sans réseau)."""

from typing import Any

import httpx
import pytest

from app.sources.cloudflare import CloudflareFallbackTransport, is_cloudflare_challenge

CHALLENGE = {"cf-mitigated": "challenge", "server": "cloudflare"}


class _FakeCurlResponse:
    def __init__(self, status: int, body: bytes, headers: dict[str, str]) -> None:
        self.status_code = status
        self.content = body
        self._headers = headers

    @property
    def headers(self) -> Any:
        items = list(self._headers.items())

        class _Headers:
            def multi_items(self) -> list[tuple[str, str]]:
                return items

        return _Headers()


class _FakeSession:
    def __init__(self, calls: list[str], status: int = 200) -> None:
        self.calls = calls
        self.status = status

    def request(self, method: str, url: str, **_: Any) -> _FakeCurlResponse:
        self.calls.append(url)
        return _FakeCurlResponse(
            self.status,
            b'{"ok": true}',
            {"content-type": "application/json", "content-encoding": "gzip"}
            | (CHALLENGE if self.status == 403 else {}),
        )


def _transport(
    monkeypatch: pytest.MonkeyPatch,
    inner_calls: list[str],
    fallback_calls: list[str],
    *,
    challenge_hosts: set[str],
    fallback_status: int = 200,
) -> CloudflareFallbackTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        inner_calls.append(str(request.url))
        if request.url.host in challenge_hosts:
            return httpx.Response(403, headers=CHALLENGE, text="Just a moment...")
        return httpx.Response(200, json={"direct": True})

    session = _FakeSession(fallback_calls, fallback_status)
    monkeypatch.setattr("curl_cffi.requests.Session", lambda **_: session)
    return CloudflareFallbackTransport(httpx.MockTransport(handler))


def test_challenge_is_replayed_with_browser_fingerprint(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    inner: list[str] = []
    fallback: list[str] = []
    transport = _transport(
        monkeypatch, inner, fallback, challenge_hosts={"shop.example"}
    )
    with httpx.Client(transport=transport) as client:
        first = client.get("https://shop.example/products/a.js")
        second = client.get("https://shop.example/products/b.js")
        other = client.get("https://open.example/products/c.js")

    assert first.status_code == 200
    assert first.json() == {"ok": True}  # corps décodé, en-tête gzip retiré
    # Hôte reconnu bloqué : la 2e requête part directement par le repli.
    assert inner == [
        "https://shop.example/products/a.js",
        "https://open.example/products/c.js",
    ]
    assert fallback == [
        "https://shop.example/products/a.js",
        "https://shop.example/products/b.js",
    ]
    assert second.status_code == 200
    assert other.json() == {"direct": True}


def test_failed_fallback_keeps_the_original_answer(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    inner: list[str] = []
    fallback: list[str] = []
    transport = _transport(
        monkeypatch,
        inner,
        fallback,
        challenge_hosts={"shop.example"},
        fallback_status=403,
    )
    with httpx.Client(transport=transport) as client:
        client.get("https://shop.example/a")
        client.get("https://shop.example/b")
    # Le repli n'a pas passé : l'hôte n'est pas mémorisé comme contournable.
    assert inner == ["https://shop.example/a", "https://shop.example/b"]


def test_plain_403_is_not_a_challenge() -> None:
    plain = httpx.Response(403, text="Forbidden")
    assert not is_cloudflare_challenge(plain)
    assert is_cloudflare_challenge(httpx.Response(403, headers=CHALLENGE))
    assert not is_cloudflare_challenge(httpx.Response(200, headers=CHALLENGE))
