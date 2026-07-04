"""Worker loop: drain the queue and run the pipeline on each item.

The pipeline itself is injected (`processor`) so the loop stays testable and
the real enrichment steps (resolve source -> copy -> images -> title ->
weights) can be wired in incrementally.

TODO(plan, Phase 2): async concurrency cap and per-host rate limiting for the
scraping steps; exponential backoff between retries.
"""

import logging
import time
from collections.abc import Callable

from sqlalchemy.orm import Session, sessionmaker

from app.jobs.queue import claim_next_item, complete_item, fail_item
from app.models import EnrichmentItem

logger = logging.getLogger(__name__)

# A processor stages results on the item (staged_* fields) and returns None.
# Raising marks the attempt as failed (requeued up to MAX_ATTEMPTS).
Processor = Callable[[Session, EnrichmentItem], None]


def process_one(db: Session, processor: Processor) -> bool:
    """Claim and process a single item. Returns False when the queue is empty."""
    item = claim_next_item(db)
    if item is None:
        return False
    try:
        processor(db, item)
    except Exception as exc:  # noqa: BLE001 — the queue owns retry semantics
        db.rollback()
        fail_item(db, item, f"{type(exc).__name__}: {exc}")
        return True
    complete_item(db, item)
    return True


def run_worker(
    session_factory: sessionmaker[Session],
    processor: Processor,
    *,
    poll_interval: float = 2.0,
    max_iterations: int | None = None,
) -> None:
    """Poll the queue forever (or `max_iterations` times, for tests)."""
    iterations = 0
    logger.info("Worker started (poll interval %.1fs)", poll_interval)
    while max_iterations is None or iterations < max_iterations:
        iterations += 1
        db = session_factory()
        try:
            worked = process_one(db, processor)
        finally:
            db.close()
        if not worked:
            time.sleep(poll_interval)
