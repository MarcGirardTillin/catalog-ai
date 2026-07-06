"""Worker service entrypoint (runs as its own process, same image as the API).

Usage:

    python worker.py

Composes the enrichment pipeline from settings and degrades explicitly:
- Xano not configured -> placeholder product reader (LOCAL DEV ONLY: items
  stage title/resolution against a minimal product, so the review loop can be
  exercised without credentials).
- Anthropic key absent -> copy generation skipped.
Image processing (Photoroom) is not wired yet (plan Phase 1).
"""

import logging

import httpx

from app.api.schemas import Product
from app.clients.claude import ClaudeClient
from app.core.config import settings
from app.core.db import SessionLocal
from app.enrich.pipeline import EnrichmentPipeline, ProductReader
from app.main import configure_application_logging

logger = logging.getLogger("worker")


def _placeholder_reader(product_id: int) -> Product:
    """LOCAL DEV ONLY — stands in for the Xano read path."""
    return Product(id=product_id, title=f"Produit {product_id}")


def _build_reader() -> ProductReader:
    if settings.xano_configured:
        from app.clients.xano import XanoClient

        client = XanoClient(
            settings.XANO_BASE_URL,
            settings.XANO_SERVICE_TOKEN,
            timeout=settings.XANO_TIMEOUT_SECONDS,
        )

        def read(product_id: int) -> Product | None:
            page = client.list_products(ids=[product_id], per_page=1)
            return page.items[0] if page.items else None

        return read

    logger.warning(
        "XANO_BASE_URL not configured — using the placeholder product reader "
        "(local dev only; staged results carry no real catalog data)."
    )
    return _placeholder_reader


def _build_claude() -> ClaudeClient | None:
    if settings.ANTHROPIC_API_KEY:
        return ClaudeClient.from_settings()
    logger.warning("ANTHROPIC_API_KEY not configured — copy generation skipped.")
    return None


def main() -> None:
    configure_application_logging()
    from app.jobs.worker import run_worker

    with httpx.Client(
        timeout=20.0, headers={"User-Agent": "CatalogAI enrichment worker"}
    ) as http_client:
        pipeline = EnrichmentPipeline(
            read_product=_build_reader(),
            http_client=http_client,
            claude=_build_claude(),
        )
        run_worker(SessionLocal, pipeline)


if __name__ == "__main__":
    main()
