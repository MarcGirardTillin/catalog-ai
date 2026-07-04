"""Enrichment job/item persistence and state transitions."""

from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.exceptions import AppException
from app.api.schemas.enrichment import JobCounts
from app.models import EnrichmentItem, EnrichmentJob

# Review transitions allowed from each current status.
_REVIEW_TRANSITIONS = {
    "approved": ("ready_for_review",),
    "rejected": ("ready_for_review", "approved"),
}


def create_job(
    db: Session,
    *,
    account_id: int,
    selection: dict[str, Any],
    config: dict[str, Any],
) -> EnrichmentJob:
    """Create a job; explicit ids become items immediately.

    TODO(plan): tag selections need a Xano read to expand into product ids —
    items for those are created by the worker once the read path has real
    credentials. The job is stored with its selection either way.
    """
    job = EnrichmentJob(
        account_id=account_id, selection_json=selection, config_json=config
    )
    db.add(job)
    db.flush()
    for product_id in selection.get("ids") or []:
        db.add(
            EnrichmentItem(
                job_id=job.id, account_id=account_id, tillin_product_id=product_id
            )
        )
    db.commit()
    db.refresh(job)
    return job


def job_counts(db: Session, job_id: int) -> JobCounts:
    rows = (
        db.execute(
            select(EnrichmentItem.status, func.count())
            .where(EnrichmentItem.job_id == job_id)
            .group_by(EnrichmentItem.status)
        )
        .tuples()
        .all()
    )
    by_status: dict[str, int] = dict(rows)
    counts = JobCounts(total=sum(by_status.values()))
    for status, count in by_status.items():
        if hasattr(counts, status):
            setattr(counts, status, count)
    return counts


def get_job(db: Session, *, account_id: int, job_id: int) -> EnrichmentJob:
    job = db.get(EnrichmentJob, job_id)
    if job is None or job.account_id != account_id:
        raise AppException(status_code=404, code="not_found", message="Job not found")
    return job


def get_item(db: Session, *, account_id: int, item_id: int) -> EnrichmentItem:
    item = db.get(EnrichmentItem, item_id)
    if item is None or item.account_id != account_id:
        raise AppException(status_code=404, code="not_found", message="Item not found")
    return item


def update_staged_fields(
    db: Session, item: EnrichmentItem, fields: dict[str, Any]
) -> EnrichmentItem:
    if item.status not in ("ready_for_review", "approved"):
        raise AppException(
            status_code=409,
            code="invalid_state",
            message=f"Cannot edit an item in status '{item.status}'",
        )
    for key, value in fields.items():
        setattr(item, key, value)
    db.commit()
    db.refresh(item)
    return item


def review_item(db: Session, item: EnrichmentItem, decision: str) -> EnrichmentItem:
    allowed_from = _REVIEW_TRANSITIONS[decision]
    if item.status not in allowed_from:
        raise AppException(
            status_code=409,
            code="invalid_state",
            message=f"Cannot mark '{item.status}' item as {decision}",
        )
    item.status = decision
    db.commit()
    db.refresh(item)
    return item
