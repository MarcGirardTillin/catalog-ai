"""Repli « navigateur » pour les sites de marque derrière Cloudflare.

Certains sites (vécu faguo-store.com, job 419) renvoient un 403
``cf-mitigated: challenge`` au client httpx du pipeline — y compris via le
proxy résidentiel — sur la seule empreinte réseau (TLS/HTTP2) : ni les
en-têtes ni le user-agent n'y changent rien, alors qu'un client à empreinte
de navigateur passe sans exécuter de JavaScript. Ce transport httpx rejoue
alors la requête via ``curl_cffi`` (impersonation Chrome) ; un hôte
reconnu bloqué passe directement par le repli pendant ``_BLOCKED_TTL``.

Tout le reste du pipeline garde son ``httpx.Client`` (MockTransport en
test, redirections, timeouts) : seul l'aller-retour réseau change.
"""

import logging
import threading
import time
from typing import Any

import httpx
from curl_cffi import requests as curl_requests

logger = logging.getLogger(__name__)

IMPERSONATE = "chrome"
_BLOCKED_TTL = 6 * 3600.0
_DEFAULT_TIMEOUT = 20.0
# En-têtes recalculés par httpx (curl_cffi rend un corps déjà décodé).
_DROPPED_HEADERS = {"content-encoding", "content-length", "transfer-encoding"}


def is_cloudflare_challenge(response: httpx.Response) -> bool:
    """403/503 d'un défi Cloudflare (pas un vrai 403 applicatif)."""
    if response.status_code not in (403, 503):
        return False
    if response.headers.get("cf-mitigated", "").lower() == "challenge":
        return True
    return "cloudflare" in response.headers.get("server", "").lower() and (
        "challenge" in response.text[:4000].lower()
    )


# Salle d'attente Akamai (« Visitor Prioritization ») : page 200 sans le
# produit, servie à une partie du trafic quand le site est chargé — y compris
# aux navigateurs (vécu patagonia.com, Neiwa, enrichissement 458 : « Résoudre »
# n'a marché qu'au 3e clic). On réessaie avec un délai avant d'abandonner.
_WAITING_ROOM_MARKERS = ("Hang Tight! Routing to checkout",)
WAITING_ROOM_DELAYS = (3.0, 6.0)
WAITING_ROOM_HEADER = "x-catalogai-waiting-room"
_BUSY_TTL = 120.0
_busy_hosts: dict[str, float] = {}
_busy_lock = threading.Lock()


class SiteBusyError(LookupError):
    """Le site de la marque fait patienter ses visiteurs (salle d'attente) :
    réessayer un peu plus tard, la page existe sans doute."""


def is_waiting_room(response: httpx.Response) -> bool:
    """Page d'attente anti-surcharge servie à la place de la vraie page."""
    if response.status_code != 200:
        return False
    if "html" not in response.headers.get("content-type", "").lower():
        return False
    head = response.read()[:4000].decode("utf-8", errors="ignore")
    return any(marker in head for marker in _WAITING_ROOM_MARKERS)


def site_is_busy(url: str) -> bool:
    """Vrai si ce site vient de nous laisser en salle d'attente (2 min)."""
    host = httpx.URL(url).host
    with _busy_lock:
        until = _busy_hosts.get(host)
        return until is not None and time.monotonic() < until


def _mark_busy(host: str) -> None:
    with _busy_lock:
        _busy_hosts[host] = time.monotonic() + _BUSY_TTL


class CloudflareFallbackTransport(httpx.BaseTransport):
    """httpx transport : réseau normal, repli curl_cffi sur défi Cloudflare."""

    def __init__(
        self,
        inner: httpx.BaseTransport | None = None,
        *,
        proxy: str | None = None,
    ) -> None:
        self._inner = inner or httpx.HTTPTransport(proxy=proxy)
        self._proxy = proxy
        self._blocked: dict[str, float] = {}
        self._lock = threading.Lock()
        self._local = threading.local()

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        response = self._send(request)
        # Site déjà en attente il y a moins de 2 min : pas de nouvelle
        # attente (un job enchaîne les requêtes vers le même site).
        delays = () if site_is_busy(str(request.url)) else WAITING_ROOM_DELAYS
        for delay in delays:
            if not is_waiting_room(response):
                return response
            logger.info(
                "waiting room on %s — retrying in %.0fs", request.url.host, delay
            )
            response.close()
            time.sleep(delay)
            response = self._send(request)
        if not is_waiting_room(response):
            return response
        # Toujours en attente : une erreur explicite plutôt qu'une page 200
        # sans produit (les appelants la traitent comme un échec).
        _mark_busy(request.url.host)
        return httpx.Response(
            503,
            headers={WAITING_ROOM_HEADER: "1", "content-type": "text/plain"},
            content=b"brand site waiting room",
            request=request,
        )

    def _send(self, request: httpx.Request) -> httpx.Response:
        host = request.url.host
        if self._is_blocked(host):
            fallback = self._fallback(request)
            if fallback is not None:
                return fallback
        response = self._inner.handle_request(request)
        if not is_cloudflare_challenge(_read(response)):
            return response
        logger.info("cloudflare challenge on %s — browser-fingerprint fallback", host)
        fallback = self._fallback(request)
        if fallback is None:
            return response
        if not is_cloudflare_challenge(fallback):
            with self._lock:
                self._blocked[host] = time.monotonic() + _BLOCKED_TTL
        return fallback

    def close(self) -> None:
        self._inner.close()

    def _is_blocked(self, host: str) -> bool:
        with self._lock:
            until = self._blocked.get(host)
            if until is None:
                return False
            if time.monotonic() >= until:
                del self._blocked[host]
                return False
            return True

    def _session(self) -> Any:
        session = getattr(self._local, "session", None)
        if session is None:
            session = curl_requests.Session(impersonate=IMPERSONATE)
            self._local.session = session
        return session

    def _fallback(self, request: httpx.Request) -> httpx.Response | None:
        timeout = request.extensions.get("timeout") or {}
        read = timeout.get("read") if isinstance(timeout, dict) else None
        headers = {
            key: value
            for key, value in request.headers.items()
            # L'empreinte navigateur fournit ses propres en-têtes de base.
            if key.lower()
            not in {"user-agent", "accept-encoding", "connection", "host"}
        }
        proxies = {"http": self._proxy, "https": self._proxy} if self._proxy else None
        try:
            result = self._session().request(
                request.method,
                str(request.url),
                headers=headers,
                data=request.read() or None,
                timeout=read or _DEFAULT_TIMEOUT,
                allow_redirects=False,  # httpx suit lui-même les redirections
                proxies=proxies,
            )
        except Exception as exc:  # curl_cffi lève ses propres erreurs réseau
            logger.warning(
                "browser-fingerprint fallback failed for %s: %s", request.url, exc
            )
            return None
        return httpx.Response(
            result.status_code,
            headers=[
                (key, value)
                for key, value in result.headers.multi_items()
                if key.lower() not in _DROPPED_HEADERS
            ],
            content=result.content,
            request=request,
        )


def source_client(
    *,
    timeout: float | httpx.Timeout,
    headers: dict[str, str] | None = None,
    proxy: str | None = None,
) -> httpx.Client:
    """Client httpx pour les SITES DE MARQUE (jamais Xano ni les API
    payantes) : redirections suivies, proxy source, repli Cloudflare."""
    return httpx.Client(
        timeout=timeout,
        headers=headers,
        follow_redirects=True,
        transport=CloudflareFallbackTransport(proxy=proxy),
    )


def _read(response: httpx.Response) -> httpx.Response:
    """Charge le corps (petit : page de défi) pour l'inspecter."""
    if response.status_code in (403, 503):
        response.read()
    return response
