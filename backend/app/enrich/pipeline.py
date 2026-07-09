"""Leg A pipeline: resolve source -> title -> weights -> copy, staged on item.

This is the `Processor` the worker loop runs (see `app.jobs.worker`). Every
external dependency is injected so the pipeline degrades gracefully and stays
testable with mocked transports:

- ``read_product``: canonical product lookup (Xano read path in prod).
- ``http_client``: brand-site (Shopify JSON) resolution + source fetch.
- ``claude``: optional copy generator — skipped when not configured.

TODO(plan Phase 1): image processing (Photoroom 4:5) — until then the source
images are staged raw for review. TODO(plan Phase 3): firecrawl/unlocker
fallbacks via the resolver's ``method`` override.
"""

import logging
from collections.abc import Callable
from typing import Any

import httpx
from sqlalchemy.orm import Session, object_session

from app.api.schemas import Product
from app.api.schemas.settings import TitleCase
from app.api.services.usage import record_claude_usage
from app.clients.claude import ClaudeClient
from app.enrich.title import apply_title_template
from app.enrich.weights import map_weights
from app.models import EnrichmentItem
from app.sources.resolver import resolve_source_url
from app.sources.shopify_json import fetch_product, score_product_match

logger = logging.getLogger(__name__)

# Default per user decision (Tillin titles usually already carry the brand);
# overridable per job via config_json["title_template"] or account settings.
DEFAULT_TITLE_TEMPLATE = "{title}"

ProductReader = Callable[[int], Product | None]


def _split_product_url(url: str) -> tuple[str, str]:
    """Split a resolved `{site}/products/{handle}` URL back into its parts."""
    site, _, handle = url.rpartition("/products/")
    return site, handle


class EnrichmentPipeline:
    """Stage enrichment results on one claimed item (worker `Processor`)."""

    def __init__(
        self,
        *,
        read_product: ProductReader,
        http_client: httpx.Client,
        claude: ClaudeClient | None = None,
    ) -> None:
        self._read_product = read_product
        self._http = http_client
        self._claude = claude

    def __call__(self, db: Session, item: EnrichmentItem) -> None:
        product = self._read_product(item.tillin_product_id)
        if product is None:
            raise LookupError(
                f"product {item.tillin_product_id} not found at the source"
            )
        config: dict[str, Any] = item.job.config_json or {}

        # 1. Title template — pure, always runs.
        template = config.get("title_template") or DEFAULT_TITLE_TEMPLATE
        case: TitleCase = (
            config["title_case"]
            if config.get("title_case") in ("upper", "capitalize")
            else "none"
        )
        item.staged_title = apply_title_template(product, template, case) or None

        # 2. Resolve the product's page on the brand site(s) + job extras.
        websites = _candidate_websites(product, config)
        resolved = resolve_source_url(self._http, product, websites)
        item.source_url = resolved.url
        item.source_method = resolved.method_used or resolved.status
        item.match_score = resolved.score
        # Keep the diagnostic (why) + candidate matches for the review UI.
        item.resolution_json = {
            "reason": resolved.reason,
            "candidates": [c.model_dump() for c in resolved.candidates],
        }

        # 3. Source-dependent transforms (weights, raw source images).
        source_product: dict[str, Any] | None = None
        if resolved.status == "resolved" and resolved.url:
            site, handle = _split_product_url(resolved.url)
            source_product = fetch_product(self._http, site, handle)
        self._stage_source(item, product, source_product)

        # 4. Copy generation — optional (needs an API key).
        self._stage_copy(db, item, product, source_product, config)

    def stage_from_url(self, item: EnrichmentItem, url: str) -> None:
        """Manually (re)resolve an item from a specific source-page URL.

        Fetches the page, re-scores the match, and re-stages weights/images/copy
        exactly as an auto-resolve would — but with ``source_method='manual'``.
        Raises LookupError when the URL yields no product page.
        """
        product = self._read_product(item.tillin_product_id)
        if product is None:
            raise LookupError(
                f"product {item.tillin_product_id} not found at the source"
            )
        config: dict[str, Any] = item.job.config_json or {}
        site, handle = _split_product_url(url)
        source_product = fetch_product(self._http, site, handle)
        if source_product is None:
            raise LookupError(f"no product page at {url}")

        item.source_url = url
        item.source_method = "manual"
        item.match_score = score_product_match(product, source_product)
        self._stage_source(item, product, source_product)
        self._stage_copy(object_session(item), item, product, source_product, config)

    def _stage_source(
        self,
        item: EnrichmentItem,
        product: Product,
        source_product: dict[str, Any] | None,
    ) -> None:
        """Stage weights + raw source images from a resolved source page."""
        if not source_product:
            return
        proposals = map_weights(product.variants, source_product.get("variants") or [])
        item.staged_weights_json = proposals or None
        images = [
            {"url": str(image["src"]), "position": position}
            for position, image in enumerate(
                source_product.get("images") or [], start=1
            )
            if isinstance(image, dict) and image.get("src")
        ]
        # Raw source images for review; Photoroom 4:5 processing is TODO.
        item.staged_images_json = images or None

    def _stage_copy(
        self,
        db: Session | None,
        item: EnrichmentItem,
        product: Product,
        source_product: dict[str, Any] | None,
        config: dict[str, Any],
    ) -> None:
        """Generate FR copy — optional (needs an API key)."""
        if self._claude is None:
            logger.info("item %s: copy skipped (no AI client configured)", item.id)
            return
        copy = self._claude.generate_copy(
            _copy_context(
                product, source_product, seo_keywords=config.get("seo_keywords")
            ),
            editorial_instructions=_effective_instructions(product, config),
            model=config.get("ai_model"),
            meta_max_length=int(config.get("meta_max_length") or 160),
        )
        item.staged_description = copy.description_fr
        item.staged_meta = copy.meta_description_fr
        # Metering (M1): one input_tokens + one output_tokens event per call,
        # committed alongside the staged result by the caller.
        if db is not None and copy.usage is not None:
            record_claude_usage(
                db,
                account_id=item.account_id,
                usage=copy.usage,
                source="enrichment",
                job_id=item.job_id,
                item_id=item.id,
            )


def _candidate_websites(product: Product, config: dict[str, Any]) -> list[str]:
    """Brand sites + the job's extra sources (deduplicated, order preserved)."""
    brand_sites = product.brand.website_urls if product.brand else []
    extras = config.get("extra_website_urls") or []
    websites: list[str] = []
    for url in [*brand_sites, *extras]:
        cleaned = str(url or "").strip()
        if cleaned and cleaned not in websites:
            websites.append(cleaned)
    return websites


def _effective_instructions(product: Product, config: dict[str, Any]) -> str:
    """The copywriter's consignes: job-wide instructions, else the snapshotted
    per-category default, optionally prefixed by the boutique context."""
    instructions = str(config.get("editorial_instructions") or "")
    if not instructions:
        by_category = config.get("category_instructions") or {}
        instructions = str(by_category.get(product.category or "", "") or "")
    client_context = str(config.get("client_context") or "")
    if client_context:
        context_block = f"Contexte boutique :\n{client_context}"
        instructions = (
            f"{context_block}\n\n{instructions}" if instructions else context_block
        )
    return instructions


def _copy_context(
    product: Product,
    source_product: dict[str, Any] | None,
    *,
    seo_keywords: list[str] | None = None,
) -> dict[str, Any]:
    """Product facts handed to the copywriter (canonical + source page)."""
    ctx: dict[str, Any] = {
        "title": product.title,
        "brand": product.brand.name if product.brand else None,
        "reference": product.reference_code,
        "season": product.season,
        "category": product.category,
        "department": product.department,
        "seo_keywords": list(seo_keywords or []) or None,
    }
    if source_product:
        ctx["source_title"] = source_product.get("title")
        ctx["source_description_html"] = source_product.get("body_html")
        ctx["source_tags"] = source_product.get("tags")
    return {key: value for key, value in ctx.items() if value}
