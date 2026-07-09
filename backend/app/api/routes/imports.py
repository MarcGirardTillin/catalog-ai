"""Supplier-file import routes: upload, list, detail, staged items.

An import is an `enrichment_job` with `job_type="import"`. The uploaded file
is stored under `settings.UPLOAD_DIR` with a generated name (the original
name only lives in `selection_json["file_name"]`), then the background runner
parses/extracts it and stages `import_item` rows for review.
"""

from pathlib import Path
from typing import Annotated
from uuid import uuid4

from fastapi import APIRouter, BackgroundTasks, Query, UploadFile
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.deps import CurrentUserDep, ImportRunnerDep, SessionDep
from app.api.exceptions import AppException
from app.api.schemas import PaginatedResponse
from app.api.schemas.imports import ImportItemPublic, ImportJobCounts, ImportJobPublic
from app.api.services.accounts import resolve_account_id
from app.core.config import settings
from app.models import EnrichmentJob, ImportItem

router = APIRouter(prefix="/imports", tags=["imports"])

ALLOWED_EXTENSIONS = (".pdf", ".xlsx", ".csv")
MAX_UPLOAD_BYTES = 20 * 1024 * 1024  # 20 MB


def _job_counts(db: Session, job_id: int) -> ImportJobCounts:
    rows = (
        db.execute(
            select(ImportItem.status, func.count())
            .where(ImportItem.job_id == job_id)
            .group_by(ImportItem.status)
        )
        .tuples()
        .all()
    )
    by_status: dict[str, int] = dict(rows)
    return ImportJobCounts(
        total=sum(by_status.values()),
        ready_for_review=by_status.get("ready_for_review", 0),
        failed=by_status.get("failed", 0),
    )


def _to_public(db: Session, job: EnrichmentJob) -> ImportJobPublic:
    config = job.config_json or {}
    duration: float | None = None
    if job.started_at is not None and job.finished_at is not None:
        duration = (job.finished_at - job.started_at).total_seconds()
    return ImportJobPublic(
        id=job.id,
        status=job.status,
        file_name=str((job.selection_json or {}).get("file_name") or ""),
        counts=_job_counts(db, job.id),
        warnings=[str(w) for w in config.get("warnings") or []],
        error=config.get("error"),
        created_at=job.created_at,
        started_at=job.started_at,
        finished_at=job.finished_at,
        duration_seconds=duration,
    )


def _get_import_job(db: Session, *, account_id: int, job_id: int) -> EnrichmentJob:
    job = db.get(EnrichmentJob, job_id)
    if job is None or job.account_id != account_id or job.job_type != "import":
        raise AppException(
            status_code=404, code="not_found", message="Import not found"
        )
    return job


@router.post("", response_model=ImportJobPublic, status_code=201)
def create_import(
    file: UploadFile,
    db: SessionDep,
    current_user: CurrentUserDep,
    background: BackgroundTasks,
    run_import: ImportRunnerDep,
) -> ImportJobPublic:
    """Upload a supplier file and start extracting products in the background."""
    original_name = file.filename or ""
    extension = Path(original_name).suffix.lower()
    if extension not in ALLOWED_EXTENSIONS:
        raise AppException(
            status_code=422,
            code="unsupported_file_type",
            message="Unsupported file type: expected .pdf, .xlsx or .csv",
        )
    data = file.file.read(MAX_UPLOAD_BYTES + 1)
    if len(data) > MAX_UPLOAD_BYTES:
        raise AppException(
            status_code=413,
            code="file_too_large",
            message="File exceeds the 20 MB upload limit",
        )

    # Stored under a generated name: no collisions, no hostile path segments.
    upload_dir = Path(settings.UPLOAD_DIR)
    upload_dir.mkdir(parents=True, exist_ok=True)
    stored_path = upload_dir / f"{uuid4().hex}{extension}"
    stored_path.write_bytes(data)

    account_id = resolve_account_id(db, current_user)
    job = EnrichmentJob(
        account_id=account_id,
        job_type="import",
        selection_json={"file_name": original_name, "file_path": str(stored_path)},
        config_json={},
    )
    db.add(job)
    db.commit()
    db.refresh(job)
    background.add_task(run_import, job.id)
    return _to_public(db, job)


@router.get("", response_model=PaginatedResponse[ImportJobPublic])
def list_imports(
    db: SessionDep,
    current_user: CurrentUserDep,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 20,
) -> PaginatedResponse[ImportJobPublic]:
    account_id = resolve_account_id(db, current_user)
    base = select(EnrichmentJob).where(
        EnrichmentJob.account_id == account_id, EnrichmentJob.job_type == "import"
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


@router.get("/{import_id}", response_model=ImportJobPublic)
def read_import(
    import_id: int, db: SessionDep, current_user: CurrentUserDep
) -> ImportJobPublic:
    account_id = resolve_account_id(db, current_user)
    return _to_public(db, _get_import_job(db, account_id=account_id, job_id=import_id))


@router.get("/{import_id}/items", response_model=PaginatedResponse[ImportItemPublic])
def list_import_items(
    import_id: int,
    db: SessionDep,
    current_user: CurrentUserDep,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 20,
) -> PaginatedResponse[ImportItemPublic]:
    """List the products staged by an import (review queue)."""
    account_id = resolve_account_id(db, current_user)
    job = _get_import_job(db, account_id=account_id, job_id=import_id)
    base = select(ImportItem).where(ImportItem.job_id == job.id)
    total = db.scalar(select(func.count()).select_from(base.subquery())) or 0
    rows = (
        db.execute(
            base.order_by(ImportItem.id).offset((page - 1) * page_size).limit(page_size)
        )
        .scalars()
        .all()
    )
    return PaginatedResponse(
        items=[
            ImportItemPublic(
                id=item.id,
                status=item.status,
                payload=item.payload_json or {},
                warnings=[str(w) for w in item.warnings_json or []],
                error=item.error,
                created_at=item.created_at,
            )
            for item in rows
        ],
        total=total,
        page=page,
        page_size=page_size,
        total_pages=(total + page_size - 1) // page_size,
    )
