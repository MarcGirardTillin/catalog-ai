"""Extraction schema.org/Product (JSON-LD) — signal structuré GRATUIT.

Reco du rapport deep-research (2026-07-18) : quand une page de marque publie
un bloc `<script type="application/ld+json">` de type Product, il porte
souvent titre, description, images, identifiants (gtin/sku/mpn) et couleur —
un GET plafonné suffit, aucune extraction LLM payante. C'est un signal
OPPORTUNISTE (jamais garanti : le JSON-LD Shopify par défaut n'a ni gtin ni
sku ni color) : l'appelant retombe sur l'extraction web quand il est absent
ou trop pauvre. Sortie au même format « Shopify-shaped » que
``firecrawl_source.extract_source_product``.
"""

import json
import logging
import re
from typing import Any

import httpx

logger = logging.getLogger(__name__)

_MAX_BYTES = 524_288
_TIMEOUT = httpx.Timeout(10.0)
_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/126.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml",
}

_LDJSON_PATTERN = re.compile(
    r"<script[^>]+type=[\"']application/ld\+json[\"'][^>]*>(.*?)</script>",
    re.IGNORECASE | re.DOTALL,
)

_ID_KEYS = ("gtin", "gtin8", "gtin12", "gtin13", "gtin14", "sku", "mpn", "productID")


def _iter_nodes(payload: Any) -> list[dict[str, Any]]:
    """Flatten a JSON-LD payload (object, list, or @graph) into nodes."""
    if isinstance(payload, list):
        nodes: list[dict[str, Any]] = []
        for entry in payload:
            nodes.extend(_iter_nodes(entry))
        return nodes
    if isinstance(payload, dict):
        if isinstance(payload.get("@graph"), list):
            return _iter_nodes(payload["@graph"])
        return [payload]
    return []


def _is_product(node: dict[str, Any]) -> bool:
    node_type = node.get("@type")
    types = node_type if isinstance(node_type, list) else [node_type]
    return any(str(t).lower() in {"product", "productgroup"} for t in types if t)


def _images_of(node: dict[str, Any]) -> list[str]:
    raw = node.get("image")
    values = raw if isinstance(raw, list) else [raw]
    urls: list[str] = []
    for value in values:
        if isinstance(value, str) and value.strip():
            urls.append(value.strip())
        elif isinstance(value, dict):  # ImageObject
            url = str(value.get("url") or value.get("contentUrl") or "").strip()
            if url:
                urls.append(url)
    return urls


def _to_source_product(node: dict[str, Any]) -> dict[str, Any] | None:
    """Map a schema.org Product node onto the Shopify-shaped source dict."""
    title = str(node.get("name") or "").strip()
    if not title:
        return None
    references: list[str] = []
    for key in _ID_KEYS:
        value = node.get(key)
        if isinstance(value, str | int) and str(value).strip():
            references.append(str(value).strip())
    # Offers may carry the identifiers instead of the product node.
    offers = node.get("offers")
    offer_list = offers if isinstance(offers, list) else [offers]
    price: str | None = None
    currency: str | None = None
    for offer in offer_list:
        if isinstance(offer, dict):
            for key in _ID_KEYS:
                value = offer.get(key)
                if isinstance(value, str | int) and str(value).strip():
                    references.append(str(value).strip())
            raw_price = offer.get("price")
            spec = offer.get("priceSpecification")
            if raw_price is None and isinstance(spec, dict):
                raw_price = spec.get("price")
            if price is None and isinstance(raw_price, str | int | float):
                text = str(raw_price).strip()
                if text:
                    price = text
            # Devise de l'offre : garde-fou avant de proposer un prix (les
            # locales /gb servent des £ — vécu dedicatedbrand 2026-08-22).
            raw_currency = offer.get("priceCurrency")
            if raw_currency is None and isinstance(spec, dict):
                raw_currency = spec.get("priceCurrency")
            if currency is None and isinstance(raw_currency, str):
                cleaned = raw_currency.strip().upper()
                if cleaned:
                    currency = cleaned
    images = _images_of(node)
    color = node.get("color")
    description = str(node.get("description") or "").strip() or None
    # Trop pauvre pour servir de source (ni identifiant ni visuel ni texte) :
    # laisser la main à l'extraction web.
    if not references and not images and not description:
        return None
    return {
        "title": title,
        "body_html": description,
        "images": [{"src": url} for url in images],
        "variants": [],
        "tags": None,
        "_jsonld": True,
        "_reference_codes": list(dict.fromkeys(references)),
        "_price": price,
        "_currency": currency,
        "_color": str(color).strip()
        if isinstance(color, str) and color.strip()
        else None,
    }


_EMBEDDED_PRICE = re.compile(r'"price"\s*:\s*"?(\d+(?:[.,]\d{1,2})?)"?')
_EMBEDDED_CURRENCY = re.compile(r'"(?:priceCurrency|currency)"\s*:\s*"([A-Za-z]{3})"')


def _embedded_price(html: str) -> tuple[str | None, str | None]:
    """Prix « embarqué » (state JSON des SPA) quand le JSON-LD n'en porte pas.

    Vécu dedicatedbrand.com (T-shirt Stockholm, 2026-08-22) : le JSON-LD
    Product n'a aucune offre mais le state Next.js répète `"price":39.95`.
    On ne retient un prix que s'il est UNIQUE dans la page (sinon ambigu —
    listes de suggestions, variantes soldées…). La devise suit la même règle.
    """
    prices = {m.group(1) for m in _EMBEDDED_PRICE.finditer(html)}
    currencies = {m.group(1).upper() for m in _EMBEDDED_CURRENCY.finditer(html)}
    price = next(iter(prices)) if len(prices) == 1 else None
    currency = next(iter(currencies)) if len(currencies) == 1 else None
    return price, currency


def fetch_jsonld_product(
    url: str, *, client: httpx.Client | None = None
) -> dict[str, Any] | None:
    """Best-effort: the page's schema.org Product, Shopify-shaped, or None."""
    own_client = client is None
    # Proxy source (jamais Xano ni les API payantes) : mêmes échecs
    # transitoires anti-bot que les pages produit (amiparis/panconesi).
    from app.core.config import settings

    active = client or httpx.Client(
        timeout=_TIMEOUT,
        headers=_HEADERS,
        follow_redirects=True,
        proxy=settings.SOURCE_PROXY_URL or None,
    )
    try:
        response = active.get(url, headers=_HEADERS)
        if response.status_code >= 400:
            return None
        if "html" not in response.headers.get("content-type", ""):
            return None
        html = response.text[:_MAX_BYTES]
    except httpx.HTTPError as exc:
        logger.info("jsonld fetch failed for %s: %s", url, exc)
        return None
    finally:
        if own_client:
            active.close()

    for match in _LDJSON_PATTERN.finditer(html):
        try:
            payload = json.loads(match.group(1))
        except json.JSONDecodeError:
            continue
        for node in _iter_nodes(payload):
            if not _is_product(node):
                continue
            product = _to_source_product(node)
            if product is not None:
                if product.get("_price") is None:
                    price, currency = _embedded_price(html)
                    product["_price"] = price
                    product["_currency"] = product.get("_currency") or currency
                return product
    return None
