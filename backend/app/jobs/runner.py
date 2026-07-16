"""In-process job execution.

The API triggers `process_pending` as a background task right after a job is
created, so the review queue fills without a separate worker process running.
The standalone `worker.py` still works (same pipeline, same queue, safe to run
alongside thanks to `SELECT ... FOR UPDATE SKIP LOCKED`) for out-of-band or
higher-throughput draining.

The pipeline is built once and cached for the API process (its httpx pool and
Xano login token are reused across runs).
"""

import logging

import httpx

from app.api.schemas import Product
from app.clients.claude import ClaudeClient
from app.clients.firecrawl import FirecrawlClient
from app.clients.photoroom import PhotoroomClient
from app.core.config import settings
from app.core.db import SessionLocal
from app.enrich.pipeline import EnrichmentPipeline, ProductReader
from app.jobs.worker import process_one

logger = logging.getLogger(__name__)

_USER_AGENT = "CatalogAI enrichment worker"


def _placeholder_reader(product_id: int, account_id: int) -> Product:
    """LOCAL DEV ONLY — stands in for the Xano read path."""
    return Product(id=product_id, title=f"Produit {product_id}")


def _account_reader(product_id: int, account_id: int) -> Product | None:
    """Read a product AS the item's account (company-scoped Xano token).

    Resolved on every call — not baked at pipeline build time — because the
    queue is shared across tenants: consecutive items can belong to different
    companies, and each read must carry the right company's token. The client
    itself is cached per account in `deps`, so this stays cheap.
    """
    from app.api.deps import xano_client_for_account

    db = SessionLocal()
    try:
        client = xano_client_for_account(db, account_id)
    finally:
        db.close()
    return client.get_product(product_id)


def _build_reader() -> ProductReader:
    if settings.xano_configured:
        return _account_reader

    logger.warning(
        "XANO not configured — using the placeholder product reader "
        "(local dev only; staged results carry no real catalog data)."
    )
    return _placeholder_reader


def _build_claude() -> ClaudeClient | None:
    if settings.ANTHROPIC_API_KEY:
        return ClaudeClient.from_settings()
    logger.warning("ANTHROPIC_API_KEY not configured — copy generation skipped.")
    return None


def _build_photoroom() -> PhotoroomClient | None:
    if settings.PHOTOROOM_API_KEY:
        return PhotoroomClient.from_settings()
    logger.warning(
        "PHOTOROOM_API_KEY not configured — source images staged as raw URLs."
    )
    return None


def _build_firecrawl() -> FirecrawlClient | None:
    if settings.FIRECRAWL_API_KEY:
        return FirecrawlClient.from_settings()
    logger.warning(
        "FIRECRAWL_API_KEY not configured — non-Shopify scrape fallback skipped."
    )
    return None


def build_pipeline(http_client: httpx.Client) -> EnrichmentPipeline:
    """Compose the enrichment pipeline from settings, degrading explicitly."""
    return EnrichmentPipeline(
        read_product=_build_reader(),
        http_client=http_client,
        claude=_build_claude(),
        photoroom=_build_photoroom(),
        firecrawl=_build_firecrawl(),
    )


_pipeline: EnrichmentPipeline | None = None


def get_pipeline() -> EnrichmentPipeline:
    """Return the process-wide pipeline, building it (and its httpx pool) once."""
    global _pipeline
    if _pipeline is None:
        # follow_redirects: some brand stores (e.g. salomon.com) 301/308 their
        # suggest.json/product JSON endpoints — the chain must survive that.
        http_client = httpx.Client(
            timeout=20.0, headers={"User-Agent": _USER_AGENT}, follow_redirects=True
        )
        _pipeline = build_pipeline(http_client)
    return _pipeline


def process_pending(job_id: int) -> None:
    """Drain currently-pending items to completion (background task entrypoint).

    Claims are global (oldest pending first), so this also sweeps up stragglers
    from earlier jobs — harmless and cooperative with any running worker.
    """
    pipeline = get_pipeline()
    processed = 0
    while True:
        db = SessionLocal()
        try:
            worked = process_one(db, pipeline)
        finally:
            db.close()
        if not worked:
            break
        processed += 1
    logger.info(
        "Background run (triggered by job %s) drained %s item(s)", job_id, processed
    )
