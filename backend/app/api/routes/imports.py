"""Supplier-file import routes: upload, list, detail, staged items.

An import is an `enrichment_job` with `job_type="import"`. One or more uploaded
files are stored under `settings.UPLOAD_DIR` with generated names (the original
names only live in `selection_json["files"]`), then the background runner
parses/extracts them together and stages `import_item` rows for review.
"""

import re
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Annotated
from uuid import uuid4

from fastapi import (
    APIRouter,
    BackgroundTasks,
    File,
    Form,
    Query,
    Response,
    UploadFile,
)
from fastapi.responses import FileResponse
from pydantic import ValidationError
from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from app.api.deps import CurrentUserDep, ImportRunnerDep, SessionDep, XanoDep
from app.api.exceptions import AppException
from app.api.schemas import PaginatedResponse
from app.api.schemas.import_profiles import ImportProfileConfig
from app.api.schemas.imports import (
    ImportFilePreview,
    ImportFilePreviewSheet,
    ImportItemPublic,
    ImportItemUpdate,
    ImportJobCounts,
    ImportJobPublic,
    ImportJobTotals,
    ImportLinkResult,
    ImportLocationSelection,
    ImportProductLine,
    ImportProducts,
    ImportProfileSelection,
    ImportRenderPreview,
    ImportTransferRequest,
    ImportTransferResult,
)
from app.api.services.accounts import resolve_account_id
from app.core.config import settings
from app.imports.schema import ImportedProduct
from app.imports.selection import stored_import_files
from app.imports.tillin_csv import (
    TILLIN_CSV_COLUMNS,
    products_from_payloads,
    render_csv,
    render_rows,
)
from app.models import EnrichmentJob, ImportItem, ImportProfile

router = APIRouter(prefix="/imports", tags=["imports"])

ALLOWED_EXTENSIONS = (".pdf", ".xlsx", ".csv")
MAX_UPLOAD_BYTES = 20 * 1024 * 1024  # 20 MB

MEDIA_TYPES = {
    ".pdf": "application/pdf",
    ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    ".csv": "text/csv",
}
# Preview caps: enough to eyeball the source, small enough to stay snappy.
PREVIEW_MAX_ROWS = 100
PREVIEW_MAX_COLS = 30
PREVIEW_MAX_CELL_CHARS = 200

# Review edits may only toggle between kept and rejected.
EDITABLE_ITEM_STATUSES = ("ready_for_review", "rejected")
# Items excluded from rendering/transfer (never reach the Tillin CSV).
EXCLUDED_RENDER_STATUSES = ("rejected", "failed")
# Statuses shown in the per-import products view (kept items only).
PRODUCTS_VIEW_STATUSES = ("applied", "ready_for_review", "approved")


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


def _job_totals(db: Session, job_id: int) -> ImportJobTotals:
    """Sum quantities and order amounts over every staged variant."""
    payloads = db.scalars(
        select(ImportItem.payload_json).where(ImportItem.job_id == job_id)
    ).all()
    quantity = 0
    wholesale: Decimal | None = None
    retail: Decimal | None = None
    for payload in payloads:
        for variant in (payload or {}).get("variants") or []:
            # A variant line without an explicit quantity counts as 1 unit.
            raw_qty = variant.get("quantity")
            qty = 1 if raw_qty is None else int(raw_qty)
            quantity += qty
            for key, running in (("wholesale_price", "w"), ("retail_price", "r")):
                raw = variant.get(key)
                if raw is None:
                    continue
                try:
                    amount = qty * Decimal(str(raw))
                except InvalidOperation:
                    continue
                if running == "w":
                    wholesale = (wholesale or Decimal(0)) + amount
                else:
                    retail = (retail or Decimal(0)) + amount
    return ImportJobTotals(
        quantity=quantity, wholesale_amount=wholesale, retail_amount=retail
    )


def _to_public(db: Session, job: EnrichmentJob) -> ImportJobPublic:
    config = job.config_json or {}
    document = config.get("document") or {}
    duration: float | None = None
    if job.started_at is not None and job.finished_at is not None:
        duration = (job.finished_at - job.started_at).total_seconds()
    file_names = [entry["file_name"] for entry in stored_import_files(job)]
    return ImportJobPublic(
        id=job.id,
        status=job.status,
        # First file for the existing single-name frontend; full list alongside.
        file_name=file_names[0] if file_names else "",
        file_names=file_names,
        counts=_job_counts(db, job.id),
        totals=_job_totals(db, job.id),
        po_number=document.get("po_number"),
        supplier=document.get("supplier"),
        profile_id=config.get("profile_id"),
        location_id=config.get("location_id"),
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
    files: Annotated[list[UploadFile], File()],
    db: SessionDep,
    current_user: CurrentUserDep,
    background: BackgroundTasks,
    run_import: ImportRunnerDep,
    location_id: Annotated[int | None, Form()] = None,
    profile_id: Annotated[int | None, Form()] = None,
) -> ImportJobPublic:
    """Upload one or more supplier files and start extracting in the background.

    Several files are supported so documents that cross-reference the same
    purchase order (e.g. a PDF order + a barcode spreadsheet) are extracted and
    reconciled in one pass. An optional `profile_id` selects the render profile
    at creation time (validated for ownership).
    """
    if not files:
        raise AppException(
            status_code=422,
            code="no_file",
            message="At least one file is required",
        )
    # Validate + read every file BEFORE touching disk: a rejected upload must
    # leave no partial state (and not even create the upload directory).
    prepared: list[tuple[str, bytes]] = []
    for file in files:
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
        prepared.append((original_name, data))

    account_id = resolve_account_id(db, current_user)
    config: dict[str, object] = {}
    if location_id is not None:
        config["location_id"] = location_id
    if profile_id is not None:
        profile = db.get(ImportProfile, profile_id)
        if profile is None or profile.account_id != account_id:
            raise AppException(
                status_code=404, code="not_found", message="Import profile not found"
            )
        config["profile_id"] = profile.id

    # Stored under generated names: no collisions, no hostile path segments.
    upload_dir = Path(settings.UPLOAD_DIR)
    upload_dir.mkdir(parents=True, exist_ok=True)
    stored_files: list[dict[str, str]] = []
    for original_name, data in prepared:
        extension = Path(original_name).suffix.lower()
        stored_path = upload_dir / f"{uuid4().hex}{extension}"
        stored_path.write_bytes(data)
        stored_files.append({"file_name": original_name, "file_path": str(stored_path)})

    job = EnrichmentJob(
        account_id=account_id,
        job_type="import",
        selection_json={"files": stored_files},
        config_json=config,
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


def _get_stored_file(
    db: Session, *, account_id: int, job_id: int, index: int = 0
) -> tuple[Path, str]:
    """Resolve the on-disk stored file at `index` for an import, or 404."""
    job = _get_import_job(db, account_id=account_id, job_id=job_id)
    files = stored_import_files(job)
    if index < 0 or index >= len(files):
        raise AppException(
            status_code=404,
            code="file_not_found",
            message="Le fichier source de cet import n'est plus disponible",
        )
    entry = files[index]
    path = Path(entry["file_path"])
    if not path.name or not path.is_file():
        raise AppException(
            status_code=404,
            code="file_not_found",
            message="Le fichier source de cet import n'est plus disponible",
        )
    file_name = entry["file_name"] or path.name
    return path, file_name


@router.get("/{import_id}/file", response_class=FileResponse)
def download_import_file(
    import_id: int,
    db: SessionDep,
    current_user: CurrentUserDep,
    index: Annotated[int, Query(ge=0)] = 0,
) -> FileResponse:
    """Stream an original uploaded file (inline, for preview or download).

    `index` selects which of the import's files to stream (default 0).
    """
    account_id = resolve_account_id(db, current_user)
    path, file_name = _get_stored_file(
        db, account_id=account_id, job_id=import_id, index=index
    )
    return FileResponse(
        path,
        media_type=MEDIA_TYPES.get(path.suffix.lower(), "application/octet-stream"),
        filename=file_name,
        content_disposition_type="inline",
    )


@router.get("/{import_id}/file/preview", response_model=ImportFilePreview)
def preview_import_file(
    import_id: int,
    db: SessionDep,
    current_user: CurrentUserDep,
    index: Annotated[int, Query(ge=0)] = 0,
) -> ImportFilePreview:
    """First rows of a tabular source file; PDFs are previewed via /file.

    `index` selects which of the import's files to preview (default 0).
    """
    account_id = resolve_account_id(db, current_user)
    path, file_name = _get_stored_file(
        db, account_id=account_id, job_id=import_id, index=index
    )
    if path.suffix.lower() == ".pdf":
        return ImportFilePreview(kind="pdf", file_name=file_name)

    from app.imports.parsers import parse_file

    try:
        document = parse_file(path.read_bytes(), file_name)
    except ValueError as exc:
        raise AppException(
            status_code=422, code="unreadable_file", message=str(exc)
        ) from exc
    sheets = [
        ImportFilePreviewSheet(
            sheet=table.sheet,
            rows=[
                [str(cell)[:PREVIEW_MAX_CELL_CHARS] for cell in row[:PREVIEW_MAX_COLS]]
                for row in table.rows[:PREVIEW_MAX_ROWS]
            ],
            total_rows=len(table.rows),
            truncated=len(table.rows) > PREVIEW_MAX_ROWS,
        )
        for table in document.tables
    ]
    return ImportFilePreview(kind="tabular", file_name=file_name, sheets=sheets)


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
        items=[_item_public(item) for item in rows],
        total=total,
        page=page,
        page_size=page_size,
        total_pages=(total + page_size - 1) // page_size,
    )


def _item_public(item: ImportItem) -> ImportItemPublic:
    return ImportItemPublic(
        id=item.id,
        status=item.status,
        tillin_product_id=item.tillin_product_id,
        payload=item.payload_json or {},
        warnings=[str(w) for w in item.warnings_json or []],
        error=item.error,
        created_at=item.created_at,
    )


@router.patch("/{import_id}/items/{item_id}", response_model=ImportItemPublic)
def update_import_item(
    import_id: int,
    item_id: int,
    body: ImportItemUpdate,
    db: SessionDep,
    current_user: CurrentUserDep,
) -> ImportItemPublic:
    """Review edit: correct a staged payload and/or reject/restore the item."""
    account_id = resolve_account_id(db, current_user)
    job = _get_import_job(db, account_id=account_id, job_id=import_id)
    item = db.get(ImportItem, item_id)
    if item is None or item.job_id != job.id:
        raise AppException(
            status_code=404, code="not_found", message="Import item not found"
        )
    if body.status is not None and body.status not in EDITABLE_ITEM_STATUSES:
        raise AppException(
            status_code=400,
            code="invalid_status",
            message="status must be 'ready_for_review' or 'rejected'",
        )
    if body.payload is not None:
        try:
            product = ImportedProduct.model_validate(body.payload)
        except ValidationError as exc:
            raise AppException(
                status_code=400,
                code="invalid_payload",
                message="payload is not a valid imported product",
                detail=exc.errors(include_url=False),
            ) from exc
        item.payload_json = product.model_dump(mode="json")
    if body.status is not None:
        item.status = body.status
    db.commit()
    db.refresh(item)
    return _item_public(item)


@router.put("/{import_id}/profile", response_model=ImportJobPublic)
def set_import_profile(
    import_id: int,
    body: ImportProfileSelection,
    db: SessionDep,
    current_user: CurrentUserDep,
) -> ImportJobPublic:
    """Select (or clear, with null) the profile used to render this import."""
    account_id = resolve_account_id(db, current_user)
    job = _get_import_job(db, account_id=account_id, job_id=import_id)
    config = dict(job.config_json or {})
    if body.profile_id is None:
        config.pop("profile_id", None)
    else:
        profile = db.get(ImportProfile, body.profile_id)
        if profile is None or profile.account_id != account_id:
            raise AppException(
                status_code=404, code="not_found", message="Import profile not found"
            )
        config["profile_id"] = profile.id
    job.config_json = config  # reassigned: plain JSON columns don't track mutation
    db.commit()
    db.refresh(job)
    return _to_public(db, job)


@router.put("/{import_id}/location", response_model=ImportJobPublic)
def set_import_location(
    import_id: int,
    body: ImportLocationSelection,
    db: SessionDep,
    current_user: CurrentUserDep,
) -> ImportJobPublic:
    """Select (or clear, with null) the Tillin location targeted by this import."""
    account_id = resolve_account_id(db, current_user)
    job = _get_import_job(db, account_id=account_id, job_id=import_id)
    config = dict(job.config_json or {})
    if body.location_id is None:
        config.pop("location_id", None)
    else:
        config["location_id"] = body.location_id
    job.config_json = config  # reassigned: plain JSON columns don't track mutation
    db.commit()
    db.refresh(job)
    return _to_public(db, job)


def _resolve_render(
    db: Session, job: EnrichmentJob, profile_id_param: int | None
) -> tuple[list[list[str]], list[str]]:
    """Render the job's kept items with the requested (or selected) profile."""
    config_json = job.config_json or {}
    profile_id = (
        profile_id_param
        if profile_id_param is not None
        else config_json.get("profile_id")
    )
    if not profile_id:
        raise AppException(
            status_code=400,
            code="profile_required",
            message="Select an import profile before rendering",
        )
    profile = db.get(ImportProfile, int(profile_id))
    if profile is None or profile.account_id != job.account_id:
        raise AppException(
            status_code=404, code="not_found", message="Import profile not found"
        )
    items = db.scalars(
        select(ImportItem)
        .where(
            ImportItem.job_id == job.id,
            ImportItem.status.not_in(EXCLUDED_RENDER_STATUSES),
        )
        .order_by(ImportItem.id)
    ).all()
    document = config_json.get("document") or {}
    fallback_supplier = document.get("supplier")
    try:
        config = ImportProfileConfig.model_validate(profile.config_json or {})
        products = products_from_payloads([item.payload_json or {} for item in items])
        return render_rows(products, config, fallback_supplier=fallback_supplier)
    except ValueError as exc:  # includes pydantic.ValidationError
        raise AppException(
            status_code=400, code="invalid_profile", message=str(exc)
        ) from exc


def _slug(value: str) -> str:
    """Lowercase, alphanumerics and dashes only (for the CSV file name)."""
    return re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")


def _csv_file_name(job: EnrichmentJob) -> str:
    document = (job.config_json or {}).get("document") or {}
    supplier = _slug(str(document.get("supplier") or ""))
    suffix = _slug(str(document.get("po_number") or "")) or str(job.id)
    parts = ["import", supplier, suffix] if supplier else ["import", suffix]
    return "_".join(parts) + ".csv"


@router.get("/{import_id}/rows", response_model=ImportRenderPreview)
def preview_import_rows(
    import_id: int,
    db: SessionDep,
    current_user: CurrentUserDep,
    profile_id: Annotated[int | None, Query()] = None,
) -> ImportRenderPreview:
    """JSON preview of the Tillin import CSV (same rows as the download)."""
    account_id = resolve_account_id(db, current_user)
    job = _get_import_job(db, account_id=account_id, job_id=import_id)
    rows, warnings = _resolve_render(db, job, profile_id)
    return ImportRenderPreview(
        columns=TILLIN_CSV_COLUMNS, rows=rows, warnings=warnings, row_count=len(rows)
    )


@router.get("/{import_id}/csv")
def download_import_csv(
    import_id: int,
    db: SessionDep,
    current_user: CurrentUserDep,
    profile_id: Annotated[int | None, Query()] = None,
) -> Response:
    """Download the rendered Tillin import CSV."""
    account_id = resolve_account_id(db, current_user)
    job = _get_import_job(db, account_id=account_id, job_id=import_id)
    rows, _warnings = _resolve_render(db, job, profile_id)
    file_name = _csv_file_name(job)
    return Response(
        content=render_csv(rows),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{file_name}"'},
    )


@router.post("/{import_id}/transfer", response_model=ImportTransferResult)
def transfer_import(
    import_id: int,
    body: ImportTransferRequest,
    db: SessionDep,
    current_user: CurrentUserDep,
    xano: XanoDep,
) -> ImportTransferResult:
    """Render the CSV and push it to a Tillin location (`/product_import`).

    Every kept (non-rejected, non-failed) item is marked `applied` and the
    transfer facts are recorded on the job.
    """
    account_id = resolve_account_id(db, current_user)
    job = _get_import_job(db, account_id=account_id, job_id=import_id)
    location_id = (
        body.location_id
        if body.location_id is not None
        else (job.config_json or {}).get("location_id")
    )
    if location_id is None:
        raise AppException(
            status_code=400,
            code="location_required",
            message="Select a Tillin location before transferring",
        )
    rows, _warnings = _resolve_render(db, job, body.profile_id)
    if not rows:
        raise AppException(
            status_code=400,
            code="nothing_to_transfer",
            message="No rows to transfer (every item is rejected or failed)",
        )
    xano.product_import(
        file_name=_csv_file_name(job),
        csv_bytes=render_csv(rows).encode("utf-8"),
        location_id=int(location_id),
    )
    db.execute(
        update(ImportItem)
        .where(
            ImportItem.job_id == job.id,
            ImportItem.status.not_in(EXCLUDED_RENDER_STATUSES),
        )
        .values(status="applied")
    )
    job.config_json = {
        **(job.config_json or {}),
        "transfer": {
            "location_id": int(location_id),
            "row_count": len(rows),
            "transferred_at": datetime.now(UTC).isoformat(),
        },
    }
    db.commit()
    return ImportTransferResult(ok=True, row_count=len(rows))


@router.post("/{import_id}/link-products", response_model=ImportLinkResult)
def link_import_products(
    import_id: int,
    db: SessionDep,
    current_user: CurrentUserDep,
    xano: XanoDep,
) -> ImportLinkResult:
    """Resolve applied items to Tillin product ids by `reference_code`.

    `/product_import` returns no ids, so after a transfer each applied item is
    linked back by searching its `supplier_ref` and matching the product whose
    `reference_code` equals it (strip + case-insensitive). Idempotent: already
    linked items are only counted, unresolved refs land in `not_found`.
    """
    account_id = resolve_account_id(db, current_user)
    job = _get_import_job(db, account_id=account_id, job_id=import_id)
    if "transfer" not in (job.config_json or {}):
        raise AppException(
            status_code=400,
            code="not_transferred",
            message="This import has not been transferred to Tillin yet",
        )
    items = db.scalars(
        select(ImportItem)
        .where(ImportItem.job_id == job.id, ImportItem.status == "applied")
        .order_by(ImportItem.id)
    ).all()
    result = ImportLinkResult()
    for item in items:
        if item.tillin_product_id is not None:
            result.already_linked += 1
            continue
        supplier_ref = str((item.payload_json or {}).get("supplier_ref") or "")
        wanted = supplier_ref.strip().lower()
        if not wanted:
            result.not_found.append(supplier_ref)
            continue
        page = xano.search_products(text=supplier_ref, per_page=5)
        # Exact reference matches only (the search itself is fuzzy). Several
        # hits are fine as long as they all point at ONE product; genuinely
        # ambiguous references (distinct products) stay unresolved.
        matched_ids = {
            product.id
            for product in page.items
            if (product.reference_code or "").strip().lower() == wanted
        }
        if len(matched_ids) == 1:
            item.tillin_product_id = matched_ids.pop()
            result.linked += 1
        else:
            result.not_found.append(supplier_ref)
    db.commit()
    return result


@router.get("/{import_id}/products", response_model=ImportProducts)
def list_import_products(
    import_id: int, db: SessionDep, current_user: CurrentUserDep
) -> ImportProducts:
    """Per-import products view, built from the staged payloads (local only).

    Rejected/failed items are excluded. The linked/unlinked counters cover the
    `applied` items only — they are the ones expected to exist in Tillin.
    """
    account_id = resolve_account_id(db, current_user)
    job = _get_import_job(db, account_id=account_id, job_id=import_id)
    items = db.scalars(
        select(ImportItem)
        .where(
            ImportItem.job_id == job.id,
            ImportItem.status.in_(PRODUCTS_VIEW_STATUSES),
        )
        .order_by(ImportItem.id)
    ).all()
    lines: list[ImportProductLine] = []
    linked_count = 0
    unlinked_count = 0
    for item in items:
        payload = item.payload_json or {}
        image_urls = payload.get("image_urls") or []
        lines.append(
            ImportProductLine(
                item_id=item.id,
                status=item.status,
                supplier_ref=str(payload.get("supplier_ref") or ""),
                title=payload.get("title"),
                brand=payload.get("brand"),
                image_url=str(image_urls[0]) if image_urls else None,
                variant_count=len(payload.get("variants") or []),
                tillin_product_id=item.tillin_product_id,
            )
        )
        if item.status == "applied":
            if item.tillin_product_id is not None:
                linked_count += 1
            else:
                unlinked_count += 1
    file_names = [entry["file_name"] for entry in stored_import_files(job)]
    return ImportProducts(
        import_id=job.id,
        file_name=file_names[0] if file_names else "",
        items=lines,
        linked_count=linked_count,
        unlinked_count=unlinked_count,
    )
