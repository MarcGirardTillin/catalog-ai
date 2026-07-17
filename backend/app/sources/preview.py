"""Best-effort page preview: the og:image of a candidate product page.

The review UI shows a thumbnail next to each resolution candidate (and the
resolved source page) so the reviewer can check the colorway at a glance
without opening every page. Brand sites virtually always publish
`og:image` / `twitter:image` for social sharing; a plain capped GET on the
HTML head is enough — no scraping provider involved, no credits.
"""

import logging
import re
from html import unescape

import httpx

logger = logging.getLogger(__name__)

# Only the <head> matters; cap the read so a huge page can't hurt us.
_MAX_BYTES = 262_144
_TIMEOUT = httpx.Timeout(8.0)
# Certains sites servent une page de challenge aux UA inconnus : on s'annonce
# comme un navigateur générique (même esprit que le resolver Shopify).
_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/126.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml",
}

_META_PATTERN = re.compile(
    r"<meta[^>]+(?:property|name)=[\"'](?:og:image|og:image:url|twitter:image)[\"']"
    r"[^>]*content=[\"']([^\"']+)[\"']",
    re.IGNORECASE,
)
# L'ordre des attributs n'est pas garanti : variante content-avant-property.
_META_PATTERN_REVERSED = re.compile(
    r"<meta[^>]+content=[\"']([^\"']+)[\"']"
    r"[^>]*(?:property|name)=[\"'](?:og:image|og:image:url|twitter:image)[\"']",
    re.IGNORECASE,
)


def _extract_image(html: str, base_url: str) -> str | None:
    match = _META_PATTERN.search(html) or _META_PATTERN_REVERSED.search(html)
    if match is None:
        return None
    raw = unescape(match.group(1)).strip()
    if not raw:
        return None
    try:
        absolute = str(httpx.URL(base_url).join(raw))
    except httpx.InvalidURL:
        return None
    return absolute if absolute.startswith(("http://", "https://")) else None


def fetch_page_preview(url: str, *, client: httpx.Client | None = None) -> str | None:
    """Return the page's social-sharing image URL, or None (best-effort)."""
    own_client = client is None
    active = client or httpx.Client(
        timeout=_TIMEOUT, headers=_HEADERS, follow_redirects=True
    )
    try:
        with active.stream("GET", url) as response:
            if response.status_code >= 400:
                return None
            content_type = response.headers.get("content-type", "")
            if "html" not in content_type:
                return None
            chunks: list[bytes] = []
            read = 0
            for chunk in response.iter_bytes():
                chunks.append(chunk)
                read += len(chunk)
                if read >= _MAX_BYTES:
                    break
        html = b"".join(chunks).decode("utf-8", errors="replace")
        return _extract_image(html, str(response.url))
    except httpx.HTTPError as exc:
        logger.info("page preview failed for %s: %s", url, exc)
        return None
    finally:
        if own_client:
            active.close()
