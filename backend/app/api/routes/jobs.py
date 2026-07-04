"""Enrichment job routes: create, list, detail."""

from typing import Annotated

from fastapi import APIRouter, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.deps import CurrentUserDep, SessionDep
from app.api.schemas import PaginatedResponse
from app.api.schemas.enrichment import JobCreateRequest, JobPublic
from app.api.services.accounts import resolve_account_id
from app.api.services.enrichment import create_job, get_job, job_counts
from app.models import EnrichmentJob

router = APIRouter(prefix="/jobs", tags=["jobs"])


def _to_public(db: Session, job: EnrichmentJob) -> JobPublic:
    return JobPublic(
        id=job.id,
        status=job.status,
        selection_json=job.selection_json,
        config_json=job.config_json,
        counts=job_counts(db, job.id),
        created_at=job.created_at,
    )


@router.post("", response_model=JobPublic, status_code=201)
def create_enrichment_job(
    payload: JobCreateRequest, db: SessionDep, current_user: CurrentUserDep
) -> JobPublic:
    """Create a job and enqueue its items (fire-and-forget: returns at once)."""
    account_id = resolve_account_id(db, current_user)
    job = create_job(
        db,
        account_id=account_id,
        selection=payload.selection.model_dump(exclude_none=True),
        config=payload.config,
    )
    return _to_public(db, job)


@router.get("", response_model=PaginatedResponse[JobPublic])
def list_jobs(
    db: SessionDep,
    current_user: CurrentUserDep,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 20,
) -> PaginatedResponse[JobPublic]:
    account_id = resolve_account_id(db, current_user)
    base = select(EnrichmentJob).where(EnrichmentJob.account_id == account_id)
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


@router.get("/{job_id}", response_model=JobPublic)
def read_job(job_id: int, db: SessionDep, current_user: CurrentUserDep) -> JobPublic:
    account_id = resolve_account_id(db, current_user)
    return _to_public(db, get_job(db, account_id=account_id, job_id=job_id))
