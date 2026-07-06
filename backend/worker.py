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
            email=settings.XANO_LOGIN_EMAIL,
            password=settings.XANO_LOGIN_PASSWORD,
            data_source=settings.XANO_DATA_SOURCE,
            timeout=settings.XANO_TIMEOUT_SECONDS,
        )
        return client.get_product

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
