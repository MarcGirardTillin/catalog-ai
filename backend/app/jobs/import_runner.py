"""Import job processor: parse the uploaded supplier file, extract products,
stage one `import_item` per product.

Runs as a background task right after `POST /imports` (same in-process model
as `app.jobs.runner`), with its own session. The parsing/extraction module
(`app.imports`, built separately) is only imported lazily inside the default
factories, so this runner stays importable — and testable with fakes — while
that module is still under construction.

Timestamps use Python wall-clock time (`datetime.now(UTC)`), NOT `func.now()`:
Postgres' now() is the transaction start time, which would collapse the
started/finished window to ~0s (see `app.jobs.queue._utcnow`).
"""

import logging
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.schemas.import_profiles import ImportProfileConfig
from app.api.services.credits import consume as consume_credits
from app.api.services.usage import record_claude_usage
from app.core.config import settings
from app.core.db import SessionLocal
from app.imports.selection import stored_import_files
from app.imports.split import split_products_by_color
from app.models import EnrichmentJob, ImportItem, ImportProfile

if TYPE_CHECKING:
    from app.imports.schema import ExtractionResult, RawDocument

logger = logging.getLogger(__name__)

# Injection points (tests pass fakes; production uses the lazy defaults).
ParseFile = Callable[[bytes, str], "RawDocument"]
Extractor = Callable[["RawDocument | list[RawDocument]"], "ExtractionResult"]
BuildExtractor = Callable[[], Extractor]


def _default_parse_file(data: bytes, filename: str) -> "RawDocument":
    from app.imports.parsers import parse_file

    return parse_file(data, filename)


def _known_category_paths() -> list[str] | None:
    """Best-effort « parent > enfant » category paths from the boutique tree.

    Fed to the extractor so it maps supplier category labels onto the user's
    own arborescence. Any failure (Xano unconfigured/unreachable) yields None —
    extraction then keeps the raw supplier labels, as before.
    """
    try:
        from app.api.deps import get_xano_client

        options = get_xano_client().get_classification().get("categories", [])
    except Exception:  # noqa: BLE001 — category matching is a best-effort bonus
        logger.warning("could not load categories for extraction matching")
        return None

    by_id = {int(o["id"]): o for o in options if o.get("id") is not None}

    def path_of(cid: int, depth: int = 0) -> str:
        option = by_id.get(cid)
        if not option or depth > 6:
            return ""
        title = str(option.get("title") or "").strip()
        parent = option.get("parent_id") or 0
        prefix = path_of(int(parent), depth + 1) if parent else ""
        return f"{prefix} > {title}" if prefix else title

    paths = [p for cid in by_id if (p := path_of(cid))]
    return paths or None


def _default_build_extractor() -> Extractor:
    from app.imports.extract import build_extractor

    return build_extractor(
        settings.ANTHROPIC_API_KEY, known_categories=_known_category_paths()
    )


def run_import_job(
    job_id: int,
    *,
    parse_file: ParseFile | None = None,
    build_extractor: BuildExtractor | None = None,
) -> None:
    """Process one import job to completion (background task entrypoint)."""
    parse = parse_file or _default_parse_file
    build = build_extractor or _default_build_extractor
    db = SessionLocal()
    try:
        job = db.get(EnrichmentJob, job_id)
        if job is None or job.job_type != "import":
            logger.warning("import runner: job %s not found or not an import", job_id)
            return
        job.status = "processing"
        job.started_at = datetime.now(UTC)
        db.commit()
        try:
            _process(db, job, parse, build)
        except Exception as exc:  # noqa: BLE001 — the job row carries the error
            db.rollback()
            logger.exception("import job %s failed", job_id)
            job.status = "failed"
            job.config_json = {
                **(job.config_json or {}),
                "error": f"{type(exc).__name__}: {exc}",
            }
            job.finished_at = datetime.now(UTC)
            db.commit()
    finally:
        db.close()


def _resolve_profile(
    db: Session, job: EnrichmentJob, supplier: str | None
) -> ImportProfile | None:
    """The profile driving this import: explicit selection, else supplier match.

    Auto-attach: when no profile was chosen at upload and the extracted
    document names a supplier matching a profile's `supplier_match`
    (containment either way, both sides lowercased), that profile is attached
    to the job — so season/price/split conventions apply without the user
    re-selecting the same profile on every order. The attachment is persisted
    with the final commit and stays editable in the UI.
    """
    config = job.config_json or {}
    profile_id = config.get("profile_id")
    if profile_id:
        profile = db.get(ImportProfile, int(profile_id))
        if profile is not None and profile.account_id == job.account_id:
            return profile
        return None
    key = (supplier or "").strip().lower()
    if not key:
        return None
    profiles = db.scalars(
        select(ImportProfile)
        .where(ImportProfile.account_id == job.account_id)
        .order_by(ImportProfile.id)
    ).all()
    for profile in profiles:
        match = profile.supplier_match
        if match and (match in key or key in match):
            job.config_json = {**config, "profile_id": profile.id}
            logger.info(
                "import job %s: profile %s (%s) auto-attached via supplier %r",
                job.id,
                profile.id,
                profile.name,
                supplier,
            )
            return profile
    return None


def _process(
    db: Session, job: EnrichmentJob, parse: ParseFile, build: BuildExtractor
) -> None:
    """Parse -> extract -> stage items + usage; commit once at the end.

    Several files can back a single import (documents of the same purchase
    order): each is parsed, then ALL of them are handed to the extractor in
    one call so Claude reconciles them into one product set.
    """
    stored_files = stored_import_files(job)
    if not stored_files:
        raise ValueError("import job has no stored source files")
    documents: list[RawDocument] = []
    for entry in stored_files:
        file_path = entry["file_path"]
        if not file_path:
            raise ValueError("import job has a stored file with no path")
        file_name = entry["file_name"] or Path(file_path).name
        data = Path(file_path).read_bytes()
        documents.append(parse(data, file_name))

    extractor = build()
    result = extractor(documents)

    # Profile conventions that shape the STAGED data (not just the render):
    # explicit selection at upload, else auto-attached by supplier match.
    profile = _resolve_profile(db, job, result.document.supplier)
    products = result.products
    if profile is not None:
        profile_config = ImportProfileConfig.model_validate(profile.config_json or {})
        if profile_config.split_by_color:
            products = split_products_by_color(products)

    for product in products:
        db.add(
            ImportItem(
                job_id=job.id,
                account_id=job.account_id,
                status="ready_for_review",
                payload_json=product.model_dump(mode="json"),
            )
        )
    for usage in result.usage:
        record_claude_usage(
            db, account_id=job.account_id, usage=usage, source="import", job_id=job.id
        )
    if products:
        consume_credits(
            db,
            account_id=job.account_id,
            action="import_product",
            quantity=len(products),
            job_id=job.id,
        )
    config_updates: dict[str, object] = {}
    if result.warnings:
        # Document-level warnings live on the job (config_json — no dedicated
        # column), surfaced by the /imports routes.
        config_updates["warnings"] = [str(w) for w in result.warnings]
    document_info = result.document.model_dump(exclude_none=True)
    if document_info:
        # PO number / supplier read once per file (purchase orders).
        config_updates["document"] = document_info
    if config_updates:
        job.config_json = {**(job.config_json or {}), **config_updates}
    # 0 extracted products is a valid (empty) outcome, not a failure.
    job.status = "completed"
    job.finished_at = datetime.now(UTC)
    db.commit()
    logger.info("import job %s completed: %s product(s) staged", job.id, len(products))
