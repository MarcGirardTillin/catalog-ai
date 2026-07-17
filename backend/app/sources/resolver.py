"""Resolve which brand-site URL a Tillin product lives at.

Chain (plan): brand site(s) -> search by identifier (barcode, then reference,
then title) -> fetch candidates -> score -> confidence gate -> human fallback.
Searches every provided site and keeps the global best.

Fallback (plan Phase 3): when the Shopify JSON chain finds nothing (non-Shopify
site, broken suggest.json) and a Firecrawl client is provided, a capped
site-scoped web search + structured extraction takes over. Firecrawl credits
are metered through the caller-provided ``usage_recorder``.
"""

import logging
from collections.abc import Callable
from typing import Any, Literal

import httpx
from pydantic import BaseModel, Field

from app.api.schemas import Product
from app.clients.base import ExternalServiceError
from app.clients.firecrawl import EXTRACT_CREDITS, SEARCH_CREDITS, FirecrawlClient
from app.sources.firecrawl_source import extract_source_product, reference_matches
from app.sources.shopify_json import (
    SCORE_BARCODE,
    fetch_product,
    score_product_match,
    search_suggest,
)

logger = logging.getLogger(__name__)

# Below this score the match goes to human review instead of auto-staging.
AUTO_STAGE_THRESHOLD = 0.75

# Firecrawl fallback cost caps: at most 2 sites searched, 2 pages extracted.
FIRECRAWL_MAX_SITES = 2
FIRECRAWL_MAX_EXTRACTS = 2
FIRECRAWL_RESOLVED_SCORE = 0.9
FIRECRAWL_CANDIDATE_SCORE = 0.3

ResolveStatus = Literal["resolved", "needs_manual", "skipped"]
Method = Literal["auto", "shopify_json", "firecrawl", "unlocker"]

UsageRecorder = Callable[[int], None]


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
    # The already-extracted source product for `url` (Firecrawl path only) so
    # the pipeline can reuse it instead of paying a second extract. Excluded
    # from serialization: it never belongs in resolution_json.
    source_product: dict[str, Any] | None = Field(default=None, exclude=True)


def _single_color(product: Product) -> str | None:
    """The product's color when it is unambiguous (all variants agree).

    Boutiques usually run one product sheet per color: adding the color to the
    title query disambiguates same-model pages that differ only by colorway
    (e.g. « dark bronze » vs « dark chocolate »). A multi-color product yields
    None — appending one arbitrary color would bias the search.
    """
    colors = {v.color.strip() for v in product.variants if v.color and v.color.strip()}
    return colors.pop() if len(colors) == 1 else None


def _title_queries(product: Product) -> list[str]:
    """Title-based terms: `title + color` first (when unambiguous), then title."""
    if not product.title:
        return []
    color = _single_color(product)
    lowered = product.title.lower()
    if color and color.lower() not in lowered:
        return [f"{product.title} {color}", product.title]
    return [product.title]


def _queries(product: Product) -> list[str]:
    """Search terms in identifier-priority order. Tillin SKU is excluded."""
    queries: list[str] = []
    queries.extend(v.barcode for v in product.variants if v.barcode)
    if product.reference_code:
        queries.append(product.reference_code)
    queries.extend(_title_queries(product))
    return queries


def _web_queries(product: Product) -> list[str]:
    """Web-search terms: reference then title(+color). Barcodes are skipped —
    they are rarely indexed by web search engines."""
    queries: list[str] = []
    if product.reference_code:
        queries.append(product.reference_code)
    queries.extend(_title_queries(product))
    return queries


def _host(site: str) -> str:
    try:
        return httpx.URL(site).host or site.strip().strip("/")
    except httpx.InvalidURL:
        return site.strip().strip("/")


def resolve_source_url(
    client: httpx.Client,
    product: Product,
    website_urls: list[str],
    *,
    method: Method = "auto",
    firecrawl: FirecrawlClient | None = None,
    usage_recorder: UsageRecorder | None = None,
) -> ResolveResult:
    """Find the product's page across all candidate sites.

    ``method`` selects the chain: ``shopify_json`` never touches Firecrawl,
    ``firecrawl`` skips Shopify, ``auto`` (default) runs Shopify first and
    falls back to Firecrawl when nothing resolves and a client is provided.
    """
    if method == "unlocker":
        # TODO(plan Phase 3): Bright Data unlocker.
        return ResolveResult(
            status="skipped", reason=f"method '{method}' not implemented yet"
        )
    if not website_urls:
        return ResolveResult(status="skipped", reason="no website URL for brand")

    if method == "firecrawl":
        if firecrawl is None:
            return ResolveResult(
                status="skipped", reason="firecrawl client not configured"
            )
        return _resolve_firecrawl(firecrawl, product, website_urls, usage_recorder)

    result = _resolve_shopify(client, product, website_urls)
    if method == "auto" and result.status == "needs_manual" and firecrawl is not None:
        fallback = _resolve_firecrawl(firecrawl, product, website_urls, usage_recorder)
        # Keep the Shopify near-misses visible to the reviewer alongside the
        # Firecrawl candidates.
        fallback.candidates = (fallback.candidates + result.candidates)[:5]
        return fallback
    return result


def _resolve_shopify(
    client: httpx.Client, product: Product, website_urls: list[str]
) -> ResolveResult:
    """The Shopify JSON chain: suggest -> fetch -> score -> confidence gate."""
    candidates: list[Candidate] = []
    seen_urls: set[str] = set()

    for site in website_urls:
        for query in _queries(product):
            try:
                stubs = search_suggest(client, site, query)
            except (httpx.HTTPError, ValueError) as exc:
                # ValueError = JSONDecodeError : un site NON-Shopify répond
                # 200 avec du HTML sur /search/suggest.json (vu live : la
                # marque On) — même dégradation qu'une erreur HTTP.
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
                except (httpx.HTTPError, ValueError) as exc:
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


def _resolve_firecrawl(
    firecrawl: FirecrawlClient,
    product: Product,
    website_urls: list[str],
    usage_recorder: UsageRecorder | None,
) -> ResolveResult:
    """Site-scoped web search + structured extraction, capped for cost.

    Per site (max 2): first query with hits wins; the first 2 on-host hits
    are extracted (max 2 extracts overall). A reference/barcode match on an
    extracted page resolves immediately at score 0.9; otherwise the pages
    accumulate as low-confidence candidates for manual review.
    """
    candidates: list[Candidate] = []
    extracts = 0

    for site in website_urls[:FIRECRAWL_MAX_SITES]:
        host = _host(site)
        hits: list[dict[str, Any]] = []
        for query in _web_queries(product):
            try:
                results = firecrawl.search(f"site:{host} {query}", limit=5)
            except ExternalServiceError as exc:
                logger.warning(
                    "firecrawl search failed on %s (%r): %s", host, query, exc
                )
                continue
            if usage_recorder is not None:
                usage_recorder(SEARCH_CREDITS)
            if results:
                hits = results
                break

        on_host = [hit for hit in hits if _host(str(hit.get("url") or "")) == host][:2]
        for hit in on_host:
            if extracts >= FIRECRAWL_MAX_EXTRACTS:
                break
            url = str(hit["url"])
            try:
                extracted = extract_source_product(firecrawl, url)
            except ExternalServiceError as exc:
                logger.warning("firecrawl extract failed for %s: %s", url, exc)
                continue
            extracts += 1
            if usage_recorder is not None:
                usage_recorder(EXTRACT_CREDITS)
            if extracted is None:
                continue
            candidate = Candidate(
                url=url,
                title=extracted.get("title"),
                score=FIRECRAWL_RESOLVED_SCORE
                if reference_matches(product, extracted)
                else FIRECRAWL_CANDIDATE_SCORE,
            )
            candidates.append(candidate)
            if candidate.score >= FIRECRAWL_RESOLVED_SCORE:
                return ResolveResult(
                    status="resolved",
                    url=url,
                    score=candidate.score,
                    method_used="firecrawl",
                    candidates=candidates[:5],
                    source_product=extracted,
                )
        if extracts >= FIRECRAWL_MAX_EXTRACTS:
            break

    # Reasons are user-facing (review UI): never name the provider here.
    if candidates:
        return ResolveResult(
            status="needs_manual",
            candidates=candidates[:5],
            reason="web search found pages but none matched the product reference",
        )
    return ResolveResult(
        status="needs_manual",
        reason="no candidate found (web search returned no usable page)",
    )
