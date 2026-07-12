"""Leg A pipeline: resolve source -> title -> weights -> copy, staged on item.

This is the `Processor` the worker loop runs (see `app.jobs.worker`). Every
external dependency is injected so the pipeline degrades gracefully and stays
testable with mocked transports:

- ``read_product``: canonical product lookup (Xano read path in prod).
- ``http_client``: brand-site (Shopify JSON) resolution + source fetch.
- ``claude``: optional copy generator — skipped when not configured.
- ``photoroom``: optional image normalizer — source images stay raw URLs
  when not configured (or when one normalization fails).
- ``firecrawl``: optional scrape fallback for non-Shopify brand sites —
  resolution stays Shopify-only when not configured.

Per-job toggles live in ``config_json["transforms"]`` (``copy``/``title``/
``weights``/``images``); a missing key or block means "enabled" so older jobs
keep their behavior. ``config_json["scrape"]["default_method"]`` picks the
resolution chain (auto | shopify_json | firecrawl; default auto).
"""

import logging
from collections.abc import Callable
from dataclasses import asdict
from datetime import UTC, datetime
from typing import Any, cast

import httpx
from sqlalchemy.orm import Session, object_session

from app.api.schemas import Product
from app.api.schemas.settings import TitleCase
from app.api.services.usage import record_claude_usage, record_usage
from app.clients.base import ExternalServiceError
from app.clients.claude import ClaudeClient
from app.clients.firecrawl import EXTRACT_CREDITS, FirecrawlClient
from app.clients.photoroom import PhotoroomClient
from app.enrich.title import apply_title_template
from app.enrich.weights import map_weights
from app.imaging import staging
from app.imaging.service import (
    PHOTOROOM_SEGMENT_MODEL,
    NormalizeOptions,
    normalize_product_image,
)
from app.models import EnrichmentItem, ImageAsset
from app.sources.firecrawl_source import extract_source_product, reference_matches
from app.sources.resolver import Method, resolve_source_url
from app.sources.shopify_json import fetch_product, score_product_match

logger = logging.getLogger(__name__)

# Default per user decision (Tillin titles usually already carry the brand);
# overridable per job via config_json["title_template"] or account settings.
DEFAULT_TITLE_TEMPLATE = "{title}"

ProductReader = Callable[[int], Product | None]

_TRANSFORM_KEYS = ("copy", "title", "weights", "images")

_SCRAPE_METHODS: tuple[Method, ...] = ("auto", "shopify_json", "firecrawl", "unlocker")


def _scrape_method(config: dict[str, Any]) -> Method:
    """Per-job resolution chain: `config_json["scrape"]["default_method"]`."""
    raw = config.get("scrape")
    if isinstance(raw, dict):
        method = raw.get("default_method")
        if method in _SCRAPE_METHODS:
            return cast(Method, method)
    return "auto"


def _transforms(config: dict[str, Any]) -> dict[str, bool]:
    """Per-job transform toggles; absent block or key = enabled (frozen contract)."""
    raw = config.get("transforms")
    if not isinstance(raw, dict):
        raw = {}
    return {key: bool(raw.get(key, True)) for key in _TRANSFORM_KEYS}


def _normalize_options(config: dict[str, Any]) -> NormalizeOptions:
    """Map `config_json["image"]` onto the verb's options (defaults preserved)."""
    raw = config.get("image")
    if not isinstance(raw, dict):
        return NormalizeOptions()
    options = NormalizeOptions()
    if raw.get("bg_color"):
        options.bg_color = str(raw["bg_color"])
    if raw.get("ratio"):
        options.ratio = str(raw["ratio"])
    if raw.get("format"):
        options.fmt = str(raw["format"])
    if raw.get("quality") is not None:
        options.quality = int(raw["quality"])
    if raw.get("max_kb") is not None:
        options.max_kb = int(raw["max_kb"])
    if raw.get("remove_bg") is not None:
        options.remove_bg = bool(raw["remove_bg"])
    if raw.get("center") is not None:
        options.center = bool(raw["center"])
    return options


def _split_product_url(url: str) -> tuple[str, str]:
    """Split a resolved `{site}/products/{handle}` URL back into its parts."""
    site, _, handle = url.rpartition("/products/")
    return site, handle


def normalize_staged_entry(
    db: Session,
    item: EnrichmentItem,
    photoroom: PhotoroomClient,
    url: str,
    position: int,
    options: NormalizeOptions,
) -> dict[str, Any] | None:
    """Normalize one source image into a staged entry; None = keep the raw URL.

    Shared by the batch pipeline (``image.auto_normalize`` opt-in) and the
    per-image review action (POST /items/{id}/images/normalize). Each run
    leaves an ``image_asset`` trace row (completed with its staged file, or
    failed with the error) plus the metered usage_event; the caller commits.
    """
    asset = ImageAsset(
        account_id=item.account_id,
        product_id=item.tillin_product_id,
        verb="normalize",
        provider="photoroom",
        model=PHOTOROOM_SEGMENT_MODEL,
        status="processing",
        source_image=url,
        params_json={"options": asdict(options)},
    )
    db.add(asset)
    db.flush()  # the staging path needs the asset id
    try:
        outcome = normalize_product_image(
            url,
            options=options,
            photoroom=photoroom,
            db=db,
            account_id=item.account_id,
            job_id=item.job_id,
            item_id=item.id,
        )
    except Exception as exc:
        logger.warning(
            "item %s: normalization failed for %s — keeping the raw URL (%s)",
            item.id,
            url,
            exc,
        )
        asset.status = "failed"
        asset.error = str(exc)
        asset.finished_at = datetime.now(UTC)
        return None
    result = outcome.output
    output_path = staging.store(asset.id, 0, result.data, result.format)
    asset.staged_paths_json = [output_path]
    # Batch keeps only the output (no reposition flow): metadata for display.
    asset.staged_files_json = [
        {
            "role": "output",
            "path": output_path,
            "bytes": len(result.data),
            "width": result.width,
            "height": result.height,
            "format": result.format,
            "index": 0,
        }
    ]
    asset.status = "completed"
    asset.finished_at = datetime.now(UTC)
    asset.params_json = {**(asset.params_json or {}), "trace": result.trace}
    return {
        "url": f"/imaging/assets/{asset.id}/files/0",
        "position": position,
        "asset_id": asset.id,
        "source_url": url,
    }


class EnrichmentPipeline:
    """Stage enrichment results on one claimed item (worker `Processor`)."""

    def __init__(
        self,
        *,
        read_product: ProductReader,
        http_client: httpx.Client,
        claude: ClaudeClient | None = None,
        photoroom: PhotoroomClient | None = None,
        firecrawl: FirecrawlClient | None = None,
    ) -> None:
        self._read_product = read_product
        self._http = http_client
        self._claude = claude
        self._photoroom = photoroom
        self._firecrawl = firecrawl

    def __call__(self, db: Session, item: EnrichmentItem) -> None:
        product = self._read_product(item.tillin_product_id)
        if product is None:
            raise LookupError(
                f"product {item.tillin_product_id} not found at the source"
            )
        config: dict[str, Any] = item.job.config_json or {}
        transforms = _transforms(config)

        # 1. Title template — pure, no source needed.
        if transforms["title"]:
            template = config.get("title_template") or DEFAULT_TITLE_TEMPLATE
            case: TitleCase = (
                config["title_case"]
                if config.get("title_case") in ("upper", "capitalize")
                else "none"
            )
            item.staged_title = apply_title_template(product, template, case) or None

        # Source resolution feeds copy/weights/images only — skip it (and
        # everything downstream) when none of them is enabled. Degenerate case
        # (everything off): the item still reaches review with nothing staged.
        if not (transforms["copy"] or transforms["weights"] or transforms["images"]):
            logger.info(
                "item %s: all source-dependent transforms disabled — skipping "
                "source resolution",
                item.id,
            )
            return

        # 2. Resolve the product's page on the brand site(s) + job extras.
        websites = _candidate_websites(product, config)
        resolved = resolve_source_url(
            self._http,
            product,
            websites,
            method=_scrape_method(config),
            firecrawl=self._firecrawl,
            usage_recorder=self._firecrawl_recorder(db, item),
        )
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
            if resolved.method_used == "firecrawl":
                # Reuse the extraction the resolver already paid for.
                source_product = resolved.source_product
            else:
                site, handle = _split_product_url(resolved.url)
                source_product = fetch_product(self._http, site, handle)
        self._stage_source(db, item, product, source_product, config)

        # 4. Copy generation — optional (needs an API key + its toggle).
        self._stage_copy(db, item, product, source_product, config)

    def stage_from_url(self, item: EnrichmentItem, url: str) -> None:
        """Manually (re)resolve an item from a specific source-page URL.

        Fetches the page, re-scores the match, and re-stages weights/images/copy
        exactly as an auto-resolve would — but with ``source_method='manual'``.
        Non-Shopify URLs fall back to Firecrawl extraction when configured.
        Raises LookupError when the URL yields no product page.
        """
        product = self._read_product(item.tillin_product_id)
        if product is None:
            raise LookupError(
                f"product {item.tillin_product_id} not found at the source"
            )
        config: dict[str, Any] = item.job.config_json or {}
        db = object_session(item)

        source_product: dict[str, Any] | None = None
        site, handle = _split_product_url(url)
        if site:
            try:
                source_product = fetch_product(self._http, site, handle)
            except httpx.HTTPError as exc:
                logger.warning(
                    "item %s: shopify fetch failed for %s (%s) — trying firecrawl",
                    item.id,
                    url,
                    exc,
                )
        if source_product is not None:
            item.match_score = score_product_match(product, source_product)
        elif self._firecrawl is not None:
            try:
                source_product = extract_source_product(self._firecrawl, url)
            except ExternalServiceError as exc:
                logger.warning(
                    "item %s: firecrawl extract failed for %s (%s)",
                    item.id,
                    url,
                    exc,
                )
            else:
                self._firecrawl_recorder(db, item)(EXTRACT_CREDITS)
            if source_product is not None:
                item.match_score = (
                    0.9 if reference_matches(product, source_product) else 0.5
                )
        if source_product is None:
            raise LookupError(f"no product page at {url}")

        item.source_url = url
        item.source_method = "manual"
        self._stage_source(db, item, product, source_product, config)
        self._stage_copy(db, item, product, source_product, config)

    def _firecrawl_recorder(
        self, db: Session | None, item: EnrichmentItem
    ) -> Callable[[int], None]:
        """Closure metering Firecrawl credits against this item's job/account."""

        def record(credits: int) -> None:
            if db is None:
                return
            record_usage(
                db,
                account_id=item.account_id,
                source="enrichment",
                provider="firecrawl",
                metric="credits",
                quantity=credits,
                job_id=item.job_id,
                item_id=item.id,
                model=None,
            )

        return record

    def _stage_source(
        self,
        db: Session | None,
        item: EnrichmentItem,
        product: Product,
        source_product: dict[str, Any] | None,
        config: dict[str, Any],
    ) -> None:
        """Stage weights + source images (normalized when Photoroom is up)."""
        if not source_product:
            return
        transforms = _transforms(config)
        if transforms["weights"]:
            proposals = map_weights(
                product.variants, source_product.get("variants") or []
            )
            item.staged_weights_json = proposals or None
        if transforms["images"]:
            self._stage_images(db, item, source_product, config)

    def _stage_images(
        self,
        db: Session | None,
        item: EnrichmentItem,
        source_product: dict[str, Any],
        config: dict[str, Any],
    ) -> None:
        """Stage the source images — ORIGINALS by default (user decision
        2026-07-10): normalization is chosen per image in the review, via
        POST /items/{id}/images/normalize. A job can still opt into the old
        normalize-everything behavior with ``config_json.image.auto_normalize``.

        Every entry keeps a ``url`` key (review-UI contract). Normalized
        entries add ``asset_id``/``source_url`` and point at the staged file.
        """
        # Dédoublonné (ordre conservé) : l'extraction LLM Firecrawl peut
        # renvoyer la même URL deux fois, et chaque doublon coûterait une
        # normalisation Photoroom (constaté live sur salomon.com).
        sources: list[str] = []
        for image in source_product.get("images") or []:
            if isinstance(image, dict) and image.get("src"):
                src = str(image["src"])
                if src not in sources:
                    sources.append(src)
        image_config = config.get("image")
        auto_normalize = bool(
            isinstance(image_config, dict) and image_config.get("auto_normalize")
        )
        options = _normalize_options(config)
        entries: list[dict[str, Any]] = []
        for position, url in enumerate(sources, start=1):
            entry: dict[str, Any] | None = None
            if auto_normalize and self._photoroom is not None and db is not None:
                entry = normalize_staged_entry(
                    db, item, self._photoroom, url, position, options
                )
            entries.append(entry or {"url": url, "position": position})
        item.staged_images_json = entries or None

    def _stage_copy(
        self,
        db: Session | None,
        item: EnrichmentItem,
        product: Product,
        source_product: dict[str, Any] | None,
        config: dict[str, Any],
    ) -> None:
        """Generate FR copy — optional (needs an API key + its toggle)."""
        if not _transforms(config)["copy"]:
            logger.info("item %s: copy skipped (transform disabled)", item.id)
            return
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
