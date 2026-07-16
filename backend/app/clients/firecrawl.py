"""Firecrawl client — scrape/search fallback for non-Shopify product pages.

Contract (Firecrawl API v2, verified against the official docs):

- ``POST /v2/search``: web search, 2 credits per 10 results.
- ``POST /v2/scrape`` with a JSON format: LLM-structured extraction of one
  page, 5 credits. Plain markdown scrape stays at 1 credit.

Credit costs are exposed as module constants so callers can meter usage
(`record_usage`) themselves — this client stays storage-free.
"""

from typing import Any

import httpx

from app.clients.base import ExternalServiceError, NotConfiguredError
from app.core.config import settings

BASE_URL = "https://api.firecrawl.dev"

# Credit costs per successful call (metered by the caller).
SEARCH_CREDITS = 2  # per search of up to 10 results
EXTRACT_CREDITS = 5  # /v2/scrape in JSON (LLM-structured) mode
SCRAPE_CREDITS = 1  # /v2/scrape in markdown mode

# JSON Schema handed to Firecrawl's structured extraction for product pages.
# The technical fields (features/composition/…) usually hide in accordions or
# click-to-open "Details" panels — Firecrawl's headless render captures them,
# the prompt below points the extractor at those sections explicitly.
PRODUCT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "title": {"type": "string"},
        "description": {"type": "string"},
        "images": {
            "type": "array",
            "items": {"type": "string"},
            "description": "URLs of the high-resolution product visuals",
        },
        "reference_codes": {
            "type": "array",
            "items": {"type": "string"},
            "description": "Reference codes, SKUs or EAN/barcodes visible on the page",
        },
        "color": {"type": "string"},
        "material": {"type": "string"},
        "price": {"type": "string"},
        "features": {
            "type": "array",
            "items": {"type": "string"},
            "description": (
                "Technical characteristics/specification bullet points, often "
                "in an accordion or a « Détails »/« Caractéristiques » section"
            ),
        },
        "composition": {
            "type": "string",
            "description": "Fabric/material composition, e.g. « 100% coton »",
        },
        "manufacturing_country": {
            "type": "string",
            "description": "Country of manufacture, e.g. « Italie »",
        },
        "care": {
            "type": "string",
            "description": "Care/washing instructions",
        },
    },
    "required": ["title"],
}

_EXTRACT_PROMPT = (
    "This is an e-commerce product page. Extract the product's title, its "
    "marketing description, the URLs of the high-resolution product images, "
    "and every reference code, SKU or EAN/barcode visible on the page. "
    "Also extract the technical details when the page carries them — "
    "characteristics/specifications, fabric composition, country of "
    "manufacture, care instructions — including those inside accordion or "
    "click-to-open sections such as « Détails » or « Caractéristiques ». "
    "Omit any field that is not present on the page; never invent values."
)


class FirecrawlClient:
    def __init__(
        self,
        api_key: str,
        *,
        timeout: float = 60.0,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        if not api_key:
            raise NotConfiguredError("firecrawl")
        self._client = httpx.Client(
            base_url=BASE_URL,
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=timeout,
            transport=transport,
        )

    @classmethod
    def from_settings(
        cls, *, transport: httpx.BaseTransport | None = None
    ) -> "FirecrawlClient":
        return cls(settings.FIRECRAWL_API_KEY, transport=transport)

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> "FirecrawlClient":
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def _post(self, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        try:
            response = self._client.post(path, json=payload)
        except httpx.HTTPError as exc:
            raise ExternalServiceError("firecrawl", "Firecrawl is unreachable") from exc
        if response.status_code >= 400:
            raise ExternalServiceError(
                "firecrawl",
                "Firecrawl returned an error response",
                detail={"upstream_status": response.status_code},
            )
        body = response.json()
        return body if isinstance(body, dict) else {}

    def scrape(self, url: str, *, formats: list[str] | None = None) -> dict[str, Any]:
        """Scrape one page; returns the raw Firecrawl payload (markdown etc.)."""
        payload = self._post(
            "/v2/scrape", {"url": url, "formats": formats or ["markdown"]}
        )
        data = payload.get("data", payload)
        return data if isinstance(data, dict) else {}

    def search(self, query: str, *, limit: int = 5) -> list[dict[str, Any]]:
        """Web search; returns the ``data.web`` hits (url/title/description)."""
        payload = self._post(
            "/v2/search", {"query": query, "limit": limit, "sources": ["web"]}
        )
        data = payload.get("data")
        web = data.get("web") if isinstance(data, dict) else None
        return web if isinstance(web, list) else []

    def extract_product(self, url: str) -> dict[str, Any] | None:
        """LLM-structured product extraction of one page (PRODUCT_SCHEMA).

        Returns the extracted JSON object, or None when Firecrawl produced
        no structured result for the page.
        """
        payload = self._post(
            "/v2/scrape",
            {
                "url": url,
                "formats": [
                    {
                        "type": "json",
                        "schema": PRODUCT_SCHEMA,
                        "prompt": _EXTRACT_PROMPT,
                    }
                ],
            },
        )
        data = payload.get("data")
        extracted = data.get("json") if isinstance(data, dict) else None
        return extracted if isinstance(extracted, dict) else None
