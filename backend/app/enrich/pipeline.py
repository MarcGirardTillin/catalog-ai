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
from sqlalchemy.orm import Session

from app.api.schemas import Product
from app.clients.claude import ClaudeClient
from app.enrich.title import apply_title_template
from app.enrich.weights import map_weights
from app.models import EnrichmentItem
from app.sources.resolver import resolve_source_url
from app.sources.shopify_json import fetch_product

logger = logging.getLogger(__name__)

# Plan-proposed default; overridable per job via config_json["title_template"].
DEFAULT_TITLE_TEMPLATE = "{brand} {title}"

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

    def __call__(self, db: Session, item: EnrichmentItem) -> None:  # noqa: ARG002
        product = self._read_product(item.tillin_product_id)
        if product is None:
            raise LookupError(
                f"product {item.tillin_product_id} not found at the source"
            )
        config: dict[str, Any] = item.job.config_json or {}

        # 1. Title template — pure, always runs.
        template = config.get("title_template") or DEFAULT_TITLE_TEMPLATE
        item.staged_title = apply_title_template(product, template) or None

        # 2. Resolve the product's page on the brand site(s).
        websites = product.brand.website_urls if product.brand else []
        resolved = resolve_source_url(self._http, product, websites)
        item.source_url = resolved.url
        item.source_method = resolved.method_used or resolved.status
        item.match_score = resolved.score

        # 3. Source-dependent transforms (weights, raw source images).
        source_product: dict[str, Any] | None = None
        if resolved.status == "resolved" and resolved.url:
            site, handle = _split_product_url(resolved.url)
            source_product = fetch_product(self._http, site, handle)
        if source_product:
            proposals = map_weights(
                product.variants, source_product.get("variants") or []
            )
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

        # 4. Copy generation — optional (needs an API key).
        if self._claude is not None:
            copy = self._claude.generate_copy(
                _copy_context(product, source_product),
                editorial_instructions=str(config.get("editorial_instructions") or ""),
                model=config.get("ai_model"),
            )
            item.staged_description = copy.description_fr
            item.staged_meta = copy.meta_description_fr
        else:
            logger.info("item %s: copy skipped (no AI client configured)", item.id)


def _copy_context(
    product: Product, source_product: dict[str, Any] | None
) -> dict[str, Any]:
    """Product facts handed to the copywriter (canonical + source page)."""
    ctx: dict[str, Any] = {
        "title": product.title,
        "brand": product.brand.name if product.brand else None,
        "reference": product.reference_code,
        "season": product.season,
        "category": product.category,
        "department": product.department,
    }
    if source_product:
        ctx["source_title"] = source_product.get("title")
        ctx["source_description_html"] = source_product.get("body_html")
        ctx["source_tags"] = source_product.get("tags")
    return {key: value for key, value in ctx.items() if value}
