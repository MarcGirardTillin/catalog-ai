"""Enrichment job routes: create, list, detail."""

from typing import Annotated

from fastapi import APIRouter, BackgroundTasks, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.deps import CurrentUserDep, JobRunnerDep, SessionDep, require_feature
from app.api.schemas import PaginatedResponse
from app.api.schemas.enrichment import ItemPublic, JobCreateRequest, JobPublic
from app.api.services.accounts import resolve_account_id
from app.api.services.credits import credit_grid, require_credits
from app.api.services.enrichment import (
    create_job,
    get_job,
    job_counts,
    retry_failed_items,
)
from app.models import EnrichmentItem, EnrichmentJob
from app.models.enrichment import ITEM_STATUSES

# Module « Enrichissement » : offre par compte.
router = APIRouter(
    prefix="/jobs",
    tags=["jobs"],
    dependencies=[Depends(require_feature("feature_enrich"))],
)


def _effective_duration(db: Session, job: EnrichmentJob) -> float | None:
    """Sum of the items' actual processing windows (claim -> settled).

    Deliberately NOT `finished_at - started_at` on the job: a retry re-opens a
    job hours later, and the calendar window would count all the idle time in
    between. Only reported once the job has settled.
    """
    if job.status not in ("completed", "partial", "failed"):
        return None
    windows = db.execute(
        select(EnrichmentItem.started_at, EnrichmentItem.finished_at).where(
            EnrichmentItem.job_id == job.id
        )
    ).all()
    durations = [
        (finished - started).total_seconds()
        for started, finished in windows
        if started is not None and finished is not None
    ]
    return sum(durations) if durations else None


def _to_public(db: Session, job: EnrichmentJob) -> JobPublic:
    duration = _effective_duration(db, job)
    return JobPublic(
        id=job.id,
        status=job.status,
        selection_json=job.selection_json,
        config_json=job.config_json,
        counts=job_counts(db, job.id),
        created_at=job.created_at,
        started_at=job.started_at,
        finished_at=job.finished_at,
        duration_seconds=duration,
    )


@router.post("", response_model=JobPublic, status_code=201)
def create_enrichment_job(
    payload: JobCreateRequest,
    db: SessionDep,
    current_user: CurrentUserDep,
    background: BackgroundTasks,
    run_job: JobRunnerDep,
) -> JobPublic:
    """Create a job, enqueue its items, and kick off processing in the
    background (the response returns at once; the worker drains after)."""
    account_id = resolve_account_id(db, current_user)
    selection = payload.selection.model_dump(exclude_none=True)
    # Refuse the launch before any write when the balance cannot cover the
    # sheets (images consumed along the way are not pre-charged).
    n_items = len(selection.get("ids") or [])
    require_credits(
        db, account_id, n_items * credit_grid(db, account_id)["enrich_item"]
    )
    job = create_job(
        db,
        account_id=account_id,
        selection=selection,
        config=payload.config,
    )
    background.add_task(run_job, job.id)
    return _to_public(db, job)


@router.get("", response_model=PaginatedResponse[JobPublic])
def list_jobs(
    db: SessionDep,
    current_user: CurrentUserDep,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 20,
) -> PaginatedResponse[JobPublic]:
    account_id = resolve_account_id(db, current_user)
    # Import jobs have their own screen (/imports) — keep them out of Jobs.
    base = select(EnrichmentJob).where(
        EnrichmentJob.account_id == account_id,
        EnrichmentJob.job_type == "enrichment",
    )
    total = db.scalar(select(func.count()).select_from(base.subquery())) or 0
    rows = (
        db.execute(
            base.order_by(EnrichmentJob.id.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
        .scalars()
        .all()
    )
    return PaginatedResponse(
        items=[_to_public(db, job) for job in rows],
        total=total,
        page=page,
        page_size=page_size,
        total_pages=(total + page_size - 1) // page_size,
    )


@router.post("/{job_id}/retry", response_model=JobPublic)
def retry_job_failures(
    job_id: int,
    db: SessionDep,
    current_user: CurrentUserDep,
    background: BackgroundTasks,
    run_job: JobRunnerDep,
) -> JobPublic:
    """Requeue a job's failed/rejected items and kick the worker."""
    account_id = resolve_account_id(db, current_user)
    job = get_job(db, account_id=account_id, job_id=job_id)
    retry_failed_items(db, job)
    background.add_task(run_job, job.id)
    return _to_public(db, job)


@router.get("/{job_id}", response_model=JobPublic)
def read_job(job_id: int, db: SessionDep, current_user: CurrentUserDep) -> JobPublic:
    account_id = resolve_account_id(db, current_user)
    return _to_public(db, get_job(db, account_id=account_id, job_id=job_id))


@router.get("/{job_id}/items", response_model=PaginatedResponse[ItemPublic])
def list_job_items(
    job_id: int,
    db: SessionDep,
    current_user: CurrentUserDep,
    status: Annotated[str | None, Query(enum=list(ITEM_STATUSES))] = None,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 20,
) -> PaginatedResponse[ItemPublic]:
    """List a job's items, optionally filtered by status (review queue)."""
    account_id = resolve_account_id(db, current_user)
    job = get_job(db, account_id=account_id, job_id=job_id)
    base = select(EnrichmentItem).where(EnrichmentItem.job_id == job.id)
    if status is not None:
        base = base.where(EnrichmentItem.status == status)
    total = db.scalar(select(func.count()).select_from(base.subquery())) or 0
    rows = (
        db.execute(
            base.order_by(EnrichmentItem.id)
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
        .scalars()
        .all()
    )
    return PaginatedResponse(
        items=[ItemPublic.model_validate(item, from_attributes=True) for item in rows],
        total=total,
        page=page,
        page_size=page_size,
        total_pages=(total + page_size - 1) // page_size,
    )
