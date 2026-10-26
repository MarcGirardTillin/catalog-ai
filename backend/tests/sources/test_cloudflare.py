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


WAITING = (
    "<html><head><title>Hang Tight! Routing to checkout...</title></head>"
    "<body>Please wait</body></html>"
)


def test_waiting_room_is_retried_then_reported(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Vécu patagonia.com : salle d'attente Akamai servie en 200 à une partie
    # du trafic ; la vraie page passe souvent au 2e ou 3e essai.
    from app.sources import cloudflare as module

    sleeps: list[float] = []
    monkeypatch.setattr("app.sources.cloudflare.time.sleep", sleeps.append)
    monkeypatch.setattr(module, "_busy_hosts", {})
    answers = iter([WAITING, WAITING, "<html><title>Doudoune</title></html>"])

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, html=next(answers))

    with httpx.Client(
        transport=CloudflareFallbackTransport(httpx.MockTransport(handler))
    ) as c:
        page = c.get("https://brand.example/p.html")
    assert page.status_code == 200 and "Doudoune" in page.text
    assert sleeps == list(module.WAITING_ROOM_DELAYS)
    assert not module.site_is_busy("https://brand.example/p.html")

    def always_waiting(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, html=WAITING)

    sleeps.clear()
    with httpx.Client(
        transport=CloudflareFallbackTransport(httpx.MockTransport(always_waiting))
    ) as c:
        busy = c.get("https://busy.example/p.html")
        again = c.get("https://busy.example/q.html")
    assert busy.status_code == 503
    assert busy.headers[module.WAITING_ROOM_HEADER] == "1"
    assert module.site_is_busy("https://busy.example/x")
    # Site déjà en attente : la requête suivante n'attend plus.
    assert again.status_code == 503
    assert sleeps == list(module.WAITING_ROOM_DELAYS)
