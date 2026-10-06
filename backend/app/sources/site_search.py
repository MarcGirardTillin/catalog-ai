"""Recherche interne des sites NON-Shopify (Magento, WooCommerce, PrestaShop…).

Vécu Le Petit Souk (2026-10-06) : la marque tourne sous Magento 2 —
``/search/suggest.json`` y répond 404, donc la chaîne Shopify ne cherchait
jamais le code-barres, et le repli web (Firecrawl) le retire des requêtes. Or
la barre de recherche du site trouve le produit au code-barres. Cette étape
interroge la recherche du site lui-même, GRATUITEMENT (aucun crédit), par de
simples GET publics passant par le même client HTTP que les autres fetchs de
pages sources (headers + proxy ``SOURCE_PROXY_URL`` hérités).

Ce module ne fait que le transport et le parsing (gabarits de recherche,
liens produits, HTML des fiches) ; le scoring et la décision restent dans
``app.sources.resolver``.

Gabarits, par hôte (découverts une fois, mis en cache) :
1. ``WebSite.potentialAction.SearchAction.target`` du JSON-LD de la page
   d'accueil du site ;
2. gabarits connus de la plateforme détectée sur cette même page :
   Magento ``/catalogsearch/result/?q=`` + ``/search/ajax/suggest/?q=``
   (JSON ElasticSuite) ; WooCommerce Store API
   ``/wp-json/wc/store/v1/products?search=`` (JSON, cherche aussi les SKU —
   placée AVANT le ``?s=`` WordPress du SearchAction, qui ne cherche ni SKU
   ni EAN ; à défaut de SearchAction : ``/?s={q}&post_type=product``) ;
   PrestaShop : l'URL de
   recherche déclarée par ``prestashop.urls.pages.search``, sinon
   ``/index.php?controller=search&s=``.
Une plateforme non reconnue n'utilise que le SearchAction : un gabarit
deviné qui ignore la requête renverrait la page d'accueil et ses produits
mis en avant (bruit en review).

Bornes (par produit, tous sites non-Shopify confondus) : au plus
``MAX_SEARCH_GETS`` (8) GET de recherche et ``MAX_PAGE_FETCHES`` (4) GET de
fiche — une recherche qui redirige sur la fiche n'en coûte pas de plus —,
plus la découverte de la page d'accueil (1 à 3 GET : URL telle quelle, avec
slash, racine) une fois par hôte et par ``STATE_TTL_SECONDS``. Soit ≤ 12 GET
par produit en régime établi, zéro crédit.
"""

import json
import logging
import re
import threading
import time
from dataclasses import dataclass, field
from html import unescape
from typing import Any, Literal
from urllib.parse import quote_plus
from weakref import WeakKeyDictionary

import httpx

from app.sources.jsonld import iter_jsonld_nodes

logger = logging.getLogger(__name__)

# Durée de vie des connaissances par hôte (non-Shopify, gabarits) : le client
# HTTP du worker vit aussi longtemps que le process — une marque qui change
# de plateforme est re-détectée au plus tard après ce délai.
STATE_TTL_SECONDS = 6 * 3600

MAX_SEARCH_GETS = 8
MAX_PAGE_FETCHES = 4
MAX_LINKS_PER_SEARCH = 3

_MAX_BYTES = 1_572_864
# Un chemin de suggest.json qui répond ainsi n'est pas une boutique Shopify.
# 403/429/5xx/timeouts restent des échecs transitoires (anti-bot, rate-limit).
_NOT_SHOPIFY_STATUSES = {404, 405, 410}
_DEAD_TEMPLATE_STATUSES = {404, 405, 410}

Platform = Literal["magento", "woocommerce", "prestashop", "unknown"]

_Q = "{q}"


@dataclass
class _HostState:
    non_shopify_until: float = 0.0
    discovered_until: float = 0.0
    platform: Platform = "unknown"
    templates: list[str] = field(default_factory=list)
    dead: set[str] = field(default_factory=set)
    # Gabarit qui a déjà renvoyé des produits : essayé en premier ensuite.
    preferred: str | None = None


# Clé = le client HTTP : en prod, le client du worker (durée du process) ;
# en test, chaque client neuf repart d'un état vierge.
_STATES: "WeakKeyDictionary[httpx.Client, dict[str, _HostState]]" = WeakKeyDictionary()
_LOCK = threading.Lock()


@dataclass
class SearchBudget:
    """GET budget for ONE product (shared across all non-Shopify sites)."""

    searches: int = MAX_SEARCH_GETS
    pages: int = MAX_PAGE_FETCHES


@dataclass
class SitePage:
    """A fetched product-page candidate."""

    url: str
    html: str


@dataclass
class SearchHit:
    """One product link out of a site search.

    ``page`` is set when the search itself landed on the product page
    (redirect on a single result, Magento) — no second GET needed.
    ``ids`` carries identifiers the structured search result declared
    (WooCommerce Store API `sku`…), used as extra matching evidence.
    """

    url: str
    page: SitePage | None = None
    ids: list[str] = field(default_factory=list)


def _host_key(site: str) -> str:
    try:
        host = httpx.URL(site).host or site
    except httpx.InvalidURL:
        host = site
    host = host.strip().strip("/").lower()
    return host.removeprefix("www.")


def same_site(url: str, site: str) -> bool:
    return bool(url) and _host_key(url) == _host_key(site)


def _state(client: httpx.Client, site: str) -> _HostState:
    with _LOCK:
        per_client = _STATES.setdefault(client, {})
        return per_client.setdefault(_host_key(site), _HostState())


# ---------------------------------------------------------------------------
# Détection non-Shopify
# ---------------------------------------------------------------------------


def is_non_shopify_error(exc: Exception) -> bool:
    """True when a `/search/suggest.json` failure proves the site is not a
    Shopify storefront (404/405/410, or a 2xx body that is not JSON)."""
    if isinstance(exc, httpx.HTTPStatusError):
        return exc.response.status_code in _NOT_SHOPIFY_STATUSES
    # JSONDecodeError (sous-classe de ValueError) : HTML servi en 200.
    return isinstance(exc, ValueError)


def mark_non_shopify(client: httpx.Client, site: str) -> None:
    _state(client, site).non_shopify_until = time.monotonic() + STATE_TTL_SECONDS


def is_non_shopify(client: httpx.Client, site: str) -> bool:
    return _state(client, site).non_shopify_until > time.monotonic()


# ---------------------------------------------------------------------------
# Découverte des gabarits
# ---------------------------------------------------------------------------

_PLACEHOLDER = re.compile(r"\{[A-Za-z_][\w-]*\}")
_PRESTA_SEARCH_URL = re.compile(r'"search"\s*:\s*"(https?:[^"]+)"')


def _search_action_templates(html: str) -> list[str]:
    templates: list[str] = []
    for node in iter_jsonld_nodes(html):
        actions = node.get("potentialAction")
        for action in actions if isinstance(actions, list) else [actions]:
            if not isinstance(action, dict):
                continue
            kind = action.get("@type")
            kinds = kind if isinstance(kind, list) else [kind]
            if "SearchAction" not in kinds:
                continue
            targets = action.get("target")
            for target in targets if isinstance(targets, list) else [targets]:
                raw = target.get("urlTemplate") if isinstance(target, dict) else target
                if isinstance(raw, str) and _PLACEHOLDER.search(raw):
                    templates.append(_PLACEHOLDER.sub(_Q, raw.strip(), count=1))
    return templates


def _detect_platform(html: str) -> Platform:
    lowered = html.lower()
    if (
        "x-magento-init" in lowered
        or "magento_theme" in lowered
        or "mage/cookies" in lowered
    ):
        return "magento"
    if "woocommerce" in lowered:
        return "woocommerce"
    if "prestashop" in lowered:
        return "prestashop"
    return "unknown"


def _origin(url: httpx.URL) -> str:
    port = f":{url.port}" if url.port else ""
    return f"{url.scheme}://{url.host}{port}"


def _known_templates(platform: Platform, home: httpx.URL, html: str) -> list[str]:
    base = str(home.copy_with(query=None, fragment=None)).rstrip("/")
    if platform == "magento":
        return [
            f"{base}/catalogsearch/result/?q={_Q}",
            f"{base}/search/ajax/suggest/?q={_Q}",
        ]
    if platform == "woocommerce":
        return [
            f"{_origin(home)}/wp-json/wc/store/v1/products?search={_Q}&per_page=5",
            f"{base}/?s={_Q}&post_type=product",
        ]
    if platform == "prestashop":
        declared = _PRESTA_SEARCH_URL.search(html)
        if declared:
            search_url = declared.group(1).replace("\\/", "/")
            joiner = "&" if "?" in search_url else "?"
            return [f"{search_url}{joiner}controller=search&s={_Q}"]
        return [f"{base}/index.php?controller=search&s={_Q}"]
    return []


def _dedupe_templates(templates: list[str]) -> list[str]:
    seen: set[str] = set()
    unique: list[str] = []
    for template in templates:
        key = template.replace("://www.", "://").rstrip("/")
        if key not in seen:
            seen.add(key)
            unique.append(template)
    return unique


def _home_candidates(site: str) -> list[str]:
    stripped = site.strip().rstrip("/")
    candidates = [stripped, f"{stripped}/"]
    try:
        root = f"{_origin(httpx.URL(stripped))}/"
    except httpx.InvalidURL:
        return candidates
    if root not in candidates:
        candidates.append(root)
    return candidates


def _discover(client: httpx.Client, site: str) -> _HostState:
    """Search templates for a site (home page fetched once per host+TTL)."""
    state = _state(client, site)
    now = time.monotonic()
    if state.discovered_until > now:
        return state
    state.discovered_until = now + STATE_TTL_SECONDS
    page = None
    # `https://nailmatic.com/fr` (sans slash) redirige vers une 404
    # PrestaShop alors que `…/fr/` répond : on essaie les deux, puis la racine.
    for home_url in _home_candidates(site):
        page = fetch_page(client, home_url)
        if page is not None:
            break
    if page is None:
        state.templates = []
        return state
    home = httpx.URL(page.url)
    platform = _detect_platform(page.html)
    actions = _search_action_templates(page.html)
    known = _known_templates(platform, home, page.html)
    if platform == "woocommerce":
        # Store API (SKU-aware, JSON) avant le `?s=` WordPress du SearchAction
        # (qui remplace alors le gabarit `?s=…&post_type=product`).
        ordered = known[:1] + (actions or known[1:])
    else:
        ordered = actions + known
    state.platform = platform
    state.templates = _dedupe_templates(ordered)
    state.dead = set()
    logger.info(
        "site search on %s: platform=%s templates=%s",
        _host_key(site),
        platform,
        state.templates,
    )
    return state


# ---------------------------------------------------------------------------
# Fetch + parsing
# ---------------------------------------------------------------------------


def fetch_page(client: httpx.Client, url: str) -> SitePage | None:
    """GET one HTML page (redirects followed, size-capped), or None."""
    try:
        response = client.get(url, follow_redirects=True)
    except (httpx.HTTPError, httpx.InvalidURL) as exc:
        logger.info("site page fetch failed for %s: %s", url, exc)
        return None
    if response.status_code >= 400:
        return None
    if "html" not in response.headers.get("content-type", "html"):
        return None
    return SitePage(url=str(response.url), html=response.text[:_MAX_BYTES])


# Liens produits des pages de résultats, par plateforme : Magento/Hyvä
# (`product-item-link` / `product-item-photo`), WooCommerce
# (`woocommerce-LoopProduct-link`), PrestaShop (`product-thumbnail`,
# `productMiniature__…link`, `product_img_link`). `:href` (Alpine/Vue,
# gabarit JS non rendu) est exclu.
_ANCHOR = re.compile(r"<a\b[^>]*>", re.IGNORECASE)
_HREF = re.compile(r"(?<![:\w-])href=[\"']([^\"']+)[\"']", re.IGNORECASE)
_CLASS = re.compile(r"\bclass=[\"']([^\"']*)[\"']", re.IGNORECASE)
_PRODUCT_LINK_CLASSES = re.compile(
    r"product-item-link|product-item-photo|woocommerce-loopproduct-link|"
    r"product-thumbnail|productminiature__[\w-]*link|product_img_link|"
    r"product-title-link",
    re.IGNORECASE,
)
_PRESTA_MINIATURE = re.compile(r"js-product-miniature", re.IGNORECASE)


def _product_links(html: str, base_url: str) -> list[str]:
    links: list[str] = []

    def add(raw: str) -> None:
        href = unescape(raw).strip()
        if not href or href.startswith(("#", "javascript:")):
            return
        try:
            absolute = str(httpx.URL(base_url).join(href))
        except httpx.InvalidURL:
            return
        if absolute.startswith(("http://", "https://")) and absolute not in links:
            links.append(absolute)

    for anchor in _ANCHOR.finditer(html):
        tag = anchor.group(0)
        classes = _CLASS.search(tag)
        href = _HREF.search(tag)
        if classes and href and _PRODUCT_LINK_CLASSES.search(classes.group(1)):
            add(href.group(1))
    # PrestaShop : premier lien de chaque miniature produit.
    for miniature in _PRESTA_MINIATURE.finditer(html):
        window = html[miniature.end() : miniature.end() + 4000]
        for anchor in _ANCHOR.finditer(window):
            href = _HREF.search(anchor.group(0))
            if href:
                add(href.group(1))
                break
    return links


_URL_KEYS = ("url", "permalink", "link", "canonical_url")
_ID_KEYS = ("sku", "reference", "ean13", "ean", "gtin", "gtin13", "upc", "mpn")
# `type` des entrées de suggestion qui ne sont pas des fiches (ElasticSuite :
# term/category/cms_page…). Les types produit WooCommerce (simple, variable,
# grouped…) passent.
_NON_PRODUCT_KINDS = {
    "term",
    "category",
    "cms_page",
    "page",
    "post",
    "attribute",
    "brand",
    "manufacturer",
}


def _json_hits(payload: Any, site: str) -> list[SearchHit]:
    """Product URLs out of a JSON search answer (ElasticSuite suggest,
    WooCommerce Store API, PrestaShop ajax…): any dict with an on-site URL;
    dicts typed as something else than a product (terms, categories) are
    skipped."""
    hits: list[SearchHit] = []

    def walk(node: Any) -> None:
        if isinstance(node, list):
            for entry in node:
                walk(entry)
            return
        if not isinstance(node, dict):
            return
        kind = node.get("type")
        url = next(
            (
                str(node[key])
                for key in _URL_KEYS
                if isinstance(node.get(key), str) and node[key].startswith("http")
            ),
            None,
        )
        is_product = str(kind or "").lower() not in _NON_PRODUCT_KINDS
        if url and is_product and same_site(url, site):
            ids = [
                str(node[key]).strip()
                for key in _ID_KEYS
                if isinstance(node.get(key), str | int) and str(node[key]).strip()
            ]
            if all(hit.url != url for hit in hits):
                hits.append(SearchHit(url=url, ids=ids))
            return
        for value in node.values():
            if isinstance(value, list | dict):
                walk(value)

    walk(payload)
    return hits


def _parse_search(
    response: httpx.Response, request_url: str, site: str
) -> list[SearchHit]:
    content_type = response.headers.get("content-type", "")
    text = response.text
    if "json" in content_type or text.lstrip()[:1] in {"[", "{"}:
        try:
            payload = json.loads(text)
        except ValueError:
            return []
        return _json_hits(payload, site)[:MAX_LINKS_PER_SEARCH]
    final = response.url
    if (
        response.history
        and final.path != httpx.URL(request_url).path
        and same_site(str(final), site)
    ):
        # Résultat unique : la recherche redirige directement sur la fiche.
        page = SitePage(url=str(final), html=text[:_MAX_BYTES])
        return [SearchHit(url=page.url, page=page)]
    links = [link for link in _product_links(text, str(final)) if same_site(link, site)]
    return [SearchHit(url=link) for link in links[:MAX_LINKS_PER_SEARCH]]


def search_site(
    client: httpx.Client, site: str, query: str, budget: SearchBudget
) -> list[SearchHit]:
    """Run ``query`` through the site's own search; product hits (max 3).

    Templates are tried in order (the host's preferred one first) until one
    yields products; a 404/405/410 template is dropped for the host.
    """
    state = _discover(client, site)
    templates = [t for t in state.templates if t not in state.dead]
    if state.preferred in templates:
        templates.remove(state.preferred)
        templates.insert(0, state.preferred)
    for template in templates:
        if budget.searches <= 0:
            break
        url = template.replace(_Q, quote_plus(query))
        budget.searches -= 1
        try:
            response = client.get(url, follow_redirects=True)
        except (httpx.HTTPError, httpx.InvalidURL) as exc:
            logger.info("site search failed on %s (%r): %s", site, query, exc)
            continue
        if response.status_code in _DEAD_TEMPLATE_STATUSES:
            state.dead.add(template)
            continue
        if response.status_code >= 400:
            continue
        hits = _parse_search(response, url, site)
        if hits:
            state.preferred = template
            return hits
    return []


# ---------------------------------------------------------------------------
# Indices d'identifiants dans une fiche
# ---------------------------------------------------------------------------

_HTML_IDS = (
    re.compile(r"data-product-sku=[\"']([^\"']+)[\"']", re.IGNORECASE),
    re.compile(
        r"itemprop=[\"'](?:sku|gtin\d*|mpn|productID)[\"'][^>]*content=[\"']([^\"']+)[\"']",
        re.IGNORECASE,
    ),
    re.compile(
        r"content=[\"']([^\"']+)[\"'][^>]*itemprop=[\"'](?:sku|gtin\d*|mpn|productID)[\"']",
        re.IGNORECASE,
    ),
)
_OG_TITLE = re.compile(
    r"<meta[^>]+property=[\"']og:title[\"'][^>]*content=[\"']([^\"']+)[\"']",
    re.IGNORECASE,
)
_OG_DESCRIPTION = re.compile(
    r"<meta[^>]+property=[\"']og:description[\"'][^>]*content=[\"']([^\"']+)[\"']",
    re.IGNORECASE,
)
_TITLE = re.compile(r"<title[^>]*>(.*?)</title>", re.IGNORECASE | re.DOTALL)
_PRODUCT_PAGE = re.compile(
    r"og:type[\"'][^>]*content=[\"']product|itemtype=[\"']https?://schema\.org/Product[\"']",
    re.IGNORECASE,
)
_URL_TOKEN = re.compile(r"[^0-9A-Za-z]+")


def html_identifiers(html: str) -> list[str]:
    """Product identifiers declared in the page markup (Magento
    `data-product-sku`, microdata sku/gtin…)."""
    found: list[str] = []
    for pattern in _HTML_IDS:
        for match in pattern.finditer(html):
            value = unescape(match.group(1)).strip()
            if value and value not in found:
                found.append(value)
    return found


def barcode_in_page(barcode: str, page: SitePage) -> bool:
    """Exact barcode on the page: as a standalone token in the HTML, or as a
    token of the page's URL path (PrestaShop slugs `…-3760229891984.html`).

    Le jeton doit être isolé, tiret compris : la fiche sœur Le Petit Souk
    porte `W-5555500381937` (référence du lot) et ne doit PAS matcher.
    """
    code = barcode.strip()
    if len(code) < 8:
        return False
    if re.search(rf"(?<![\w-]){re.escape(code)}(?![\w-])", page.html):
        return True
    path = httpx.URL(page.url).path
    return code in _URL_TOKEN.split(path)


def looks_like_product_page(html: str) -> bool:
    if _PRODUCT_PAGE.search(html):
        return True
    for node in iter_jsonld_nodes(html):
        kind = node.get("@type")
        kinds = kind if isinstance(kind, list) else [kind]
        if any(str(k).lower() in {"product", "productgroup"} for k in kinds):
            return True
    return False


def page_text_fields(html: str) -> dict[str, str | None]:
    """Fallback title/description when the page has no JSON-LD Product."""
    title_match = _OG_TITLE.search(html) or _TITLE.search(html)
    description = _OG_DESCRIPTION.search(html)
    return {
        "title": unescape(title_match.group(1)).strip() if title_match else None,
        "body_html": unescape(description.group(1)).strip() if description else None,
    }
