"""Firecrawl client — scrape fallback for non-Shopify product pages (Leg A).

TODO(plan): confirm the current endpoint version and /extract (LLM-structured)
shape when the fallback path is actually wired in Phase 3.
"""

from typing import Any

import httpx

from app.clients.base import ExternalServiceError, NotConfiguredError
from app.core.config import settings

BASE_URL = "https://api.firecrawl.dev"


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

    def scrape(self, url: str, *, formats: list[str] | None = None) -> dict[str, Any]:
        """Scrape one page; returns the raw Firecrawl payload (markdown etc.)."""
        try:
            response = self._client.post(
                "/v2/scrape", json={"url": url, "formats": formats or ["markdown"]}
            )
        except httpx.HTTPError as exc:
            raise ExternalServiceError("firecrawl", "Firecrawl is unreachable") from exc
        if response.status_code >= 400:
            raise ExternalServiceError(
                "firecrawl",
                "Firecrawl returned an error response",
                detail={"upstream_status": response.status_code},
            )
        payload = response.json()
        return payload.get("data", payload) if isinstance(payload, dict) else {}
