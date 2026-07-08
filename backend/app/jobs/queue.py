"""Postgres-backed work queue over enrichment_item.

Claiming uses `SELECT ... FOR UPDATE SKIP LOCKED` so several worker processes
can drain the same table without stepping on each other. SQLite (tests)
silently ignores FOR UPDATE, which keeps the logic testable single-threaded.
"""

import logging
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import EnrichmentItem, EnrichmentJob
from app.models.enrichment import MAX_ATTEMPTS

logger = logging.getLogger(__name__)

# Item statuses that mean "the worker is done with this item".
_WORKER_TERMINAL = ("ready_for_review", "approved", "applied", "rejected", "failed")


def _utcnow() -> datetime:
    """Wall-clock timestamps for processing windows.

    NOT `func.now()`: Postgres' now() is the TRANSACTION start time, and the
    session's next transaction opens right after the claim commits — so claim
    and completion would carry near-identical timestamps (item durations of 0s).
    """
    return datetime.now(UTC)


def claim_next_item(db: Session) -> EnrichmentItem | None:
    """Atomically claim the oldest pending item, or return None."""
    item = db.scalars(
        select(EnrichmentItem)
        .where(EnrichmentItem.status == "pending")
        .order_by(EnrichmentItem.id)
        .limit(1)
        .with_for_update(skip_locked=True)
    ).first()
    if item is None:
        db.rollback()
        return None

    item.status = "processing"
    item.attempt_count += 1
    item.started_at = _utcnow()
    item.finished_at = None
    job = db.get(EnrichmentJob, item.job_id)
    if job is not None and job.status == "pending":
        job.status = "processing"
        if job.started_at is None:
            job.started_at = _utcnow()
    db.commit()
    db.refresh(item)
    return item


def complete_item(db: Session, item: EnrichmentItem) -> None:
    """Mark a processed item as staged and ready for human review."""
    item.status = "ready_for_review"
    item.error = None
    item.finished_at = _utcnow()
    db.commit()
    _rollup_job(db, item.job_id)


def fail_item(db: Session, item: EnrichmentItem, error: str) -> None:
    """Requeue for retry, or mark failed after MAX_ATTEMPTS.

    TODO(plan): retry with exponential backoff (tenacity) instead of an
    immediate requeue — Phase 2, together with per-host rate limiting.
    """
    item.error = error
    if item.attempt_count >= MAX_ATTEMPTS:
        item.status = "failed"
        item.finished_at = _utcnow()
        logger.error("item %s failed permanently: %s", item.id, error)
    else:
        item.status = "pending"
        logger.warning(
            "item %s attempt %s failed, requeued: %s",
            item.id,
            item.attempt_count,
            error,
        )
    db.commit()
    _rollup_job(db, item.job_id)


def _rollup_job(db: Session, job_id: int) -> None:
    """Recompute the job status once no item is pending/processing."""
    statuses = list(
        db.scalars(
            select(EnrichmentItem.status).where(EnrichmentItem.job_id == job_id)
        ).all()
    )
    if not statuses or any(s not in _WORKER_TERMINAL for s in statuses):
        return
    job = db.get(EnrichmentJob, job_id)
    if job is None:
        return
    failed = sum(1 for s in statuses if s == "failed")
    if failed == len(statuses):
        job.status = "failed"
    elif failed > 0:
        job.status = "partial"
    else:
        job.status = "completed"
    if job.finished_at is None:
        job.finished_at = _utcnow()
    db.commit()
