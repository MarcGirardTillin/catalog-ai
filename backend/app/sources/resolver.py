"""Resolve which brand-site URL a Tillin product lives at.

Chain (plan): brand site(s) -> search by identifier (barcode, then reference,
then title) -> fetch candidates -> score -> confidence gate -> human fallback.
Searches every provided site and keeps the global best.
"""

import logging
from typing import Any, Literal

import httpx
from pydantic import BaseModel, Field

from app.api.schemas import Product
from app.sources.shopify_json import (
    SCORE_BARCODE,
    fetch_product,
    score_product_match,
    search_suggest,
)

logger = logging.getLogger(__name__)

# Below this score the match goes to human review instead of auto-staging.
AUTO_STAGE_THRESHOLD = 0.75

ResolveStatus = Literal["resolved", "needs_manual", "skipped"]
Method = Literal["auto", "shopify_json", "firecrawl", "unlocker"]


class Candidate(BaseModel):
    url: str
    title: str | None = None
    score: float


class ResolveResult(BaseModel):
    status: ResolveStatus
    url: str | None = None
    score: float | None = None
    method_used: str | None = None
    candidates: list[Candidate] = Field(default_factory=list)
    reason: str | None = None


def _queries(product: Product) -> list[str]:
    """Search terms in identifier-priority order. Tillin SKU is excluded."""
    queries: list[str] = []
    queries.extend(v.barcode for v in product.variants if v.barcode)
    if product.reference_code:
        queries.append(product.reference_code)
    if product.title:
        queries.append(product.title)
    return queries


def resolve_source_url(
    client: httpx.Client,
    product: Product,
    website_urls: list[str],
    *,
    method: Method = "auto",
) -> ResolveResult:
    """Find the product's page across all candidate sites."""
    if method in ("firecrawl", "unlocker"):
        # TODO(plan Phase 3): firecrawl fallback + Bright Data unlocker.
        return ResolveResult(
            status="skipped", reason=f"method '{method}' not implemented yet"
        )
    if not website_urls:
        return ResolveResult(status="skipped", reason="no website URL for brand")

    candidates: list[Candidate] = []
    seen_urls: set[str] = set()

    for site in website_urls:
        for query in _queries(product):
            try:
                stubs = search_suggest(client, site, query)
            except httpx.HTTPError as exc:
                logger.warning("suggest failed on %s (%r): %s", site, query, exc)
                continue
            for stub in stubs:
                handle = str(stub.get("handle") or "").strip()
                if not handle:
                    continue
                url = f"{site.rstrip('/')}/products/{handle}"
                if url in seen_urls:
                    continue
                seen_urls.add(url)
                try:
                    full: dict[str, Any] | None = fetch_product(client, site, handle)
                except httpx.HTTPError as exc:
                    logger.warning("fetch failed for %s: %s", url, exc)
                    continue
                if full is None:
                    continue
                score = score_product_match(product, full)
                candidates.append(
                    Candidate(url=url, title=full.get("title"), score=score)
                )
                if score >= SCORE_BARCODE:
                    # Near-perfect (barcode) match: early exit.
                    return ResolveResult(
                        status="resolved",
                        url=url,
                        score=score,
                        method_used="shopify_json",
                        candidates=sorted(
                            candidates, key=lambda c: c.score, reverse=True
                        )[:5],
                    )

    candidates.sort(key=lambda c: c.score, reverse=True)
    if candidates and candidates[0].score >= AUTO_STAGE_THRESHOLD:
        best = candidates[0]
        return ResolveResult(
            status="resolved",
            url=best.url,
            score=best.score,
            method_used="shopify_json",
            candidates=candidates[:5],
        )
    if candidates:
        return ResolveResult(
            status="needs_manual",
            candidates=candidates[:5],
            reason="no candidate above confidence threshold",
        )
    return ResolveResult(status="needs_manual", reason="no candidate found")
