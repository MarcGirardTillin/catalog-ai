"""Enrichment job/item persistence and state transitions."""

from collections.abc import Callable
from typing import TYPE_CHECKING, Any

import httpx

if TYPE_CHECKING:
    from app.clients.photoroom import PhotoroomClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.exceptions import AppException
from app.api.schemas.enrichment import JobCounts
from app.destinations.base import Destination
from app.models import Account, EnrichmentItem, EnrichmentJob, InstructionTemplate

# Account-level defaults merged into a new job's config when absent.
_ACCOUNT_CONFIG_DEFAULTS = (
    "title_template",
    "title_case",
    "editorial_instructions",
    "client_context",
    "meta_max_length",
)

# Review transitions allowed from each current status.
_REVIEW_TRANSITIONS = {
    "approved": ("ready_for_review",),
    "rejected": ("ready_for_review", "approved"),
}


def _resolve_instruction(
    db: Session, *, account_id: int, instruction_id: int
) -> InstructionTemplate:
    instruction = db.get(InstructionTemplate, instruction_id)
    if instruction is None or instruction.account_id != account_id:
        raise AppException(
            status_code=404, code="not_found", message="Instruction not found"
        )
    return instruction


def _category_defaults(db: Session, account_id: int) -> dict[str, str]:
    """Snapshot of per-category default instructions: {category: content}.

    Templates that claim categories (`categories_json` non-empty) each map
    their categories to their content. A category claimed by several templates
    resolves to the most recent one (deterministic: rows applied in
    created_at/id order, later — newer — wins).
    """
    rows = (
        db.execute(
            select(InstructionTemplate)
            .where(InstructionTemplate.account_id == account_id)
            .order_by(InstructionTemplate.created_at, InstructionTemplate.id)
        )
        .scalars()
        .all()
    )
    defaults: dict[str, str] = {}
    for template in rows:
        for category in template.categories_json or []:
            defaults[str(category)] = template.content
    return defaults


def create_job(
    db: Session,
    *,
    account_id: int,
    selection: dict[str, Any],
    config: dict[str, Any],
) -> EnrichmentJob:
    """Create a job; explicit ids become items immediately.

    The persisted config is a snapshot: instruction templates referenced by
    ``instruction_id`` (or claimed per category) are copied into it, so later
    edits/deletions of the library never affect this job. Instruction
    precedence at copy time: explicit ``editorial_instructions`` >
    ``instruction_id`` > account default ``editorial_instructions`` >
    per-category snapshot (``category_instructions``).

    TODO(plan): tag selections need a Xano read to expand into product ids —
    items for those are created by the worker once the read path has real
    credentials. The job is stored with its selection either way.
    """
    config = dict(config)

    # A named instruction is resolved server-side and snapshotted; the id is
    # dropped from the stored config (explicit editorial_instructions win).
    instruction_id = config.pop("instruction_id", None)
    if instruction_id is not None:
        instruction = _resolve_instruction(
            db, account_id=account_id, instruction_id=int(instruction_id)
        )
        if not config.get("editorial_instructions"):
            config["editorial_instructions"] = instruction.content
    elif not config.get("editorial_instructions"):
        # No pinned instructions: snapshot the per-category defaults.
        category_defaults = _category_defaults(db, account_id)
        if category_defaults:
            config["category_instructions"] = category_defaults

    # The account's enrichment defaults apply unless the job overrides them.
    # Note: an account-level editorial_instructions default still outranks the
    # category snapshot (the pipeline prefers editorial_instructions).
    account = db.get(Account, account_id)
    defaults = (account.settings_json if account else None) or {}
    for key in _ACCOUNT_CONFIG_DEFAULTS:
        if defaults.get(key) and not config.get(key):
            config[key] = defaults[key]

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


def normalize_item_image(
    db: Session,
    item: EnrichmentItem,
    photoroom: "PhotoroomClient",
    *,
    url: str,
    revert: bool = False,
) -> EnrichmentItem:
    """Normalize (or revert) ONE staged image entry, chosen by the reviewer.

    The batch stages the original source images (user decision 2026-07-10);
    normalization is per image, on demand. ``revert`` restores the original
    URL of a normalized entry. The reviewer's partial selection
    (``apply_fields_json.image_urls``) follows the entry's new url.
    """
    from app.enrich.pipeline import (
        _normalize_options,  # noqa: PLC2701 — same package family, shared options mapping
        normalize_staged_entry,
    )
    from app.imaging import staging

    if item.status not in ("ready_for_review", "approved"):
        raise AppException(
            status_code=409,
            code="invalid_state",
            message=f"Cannot edit images of an item in status '{item.status}'",
        )
    entries = [dict(e) for e in (item.staged_images_json or [])]
    index = next((i for i, e in enumerate(entries) if e.get("url") == url), None)
    if index is None:
        raise AppException(
            status_code=404, code="not_found", message="No staged image at this url"
        )
    entry = entries[index]
    position = int(entry.get("position") or index + 1)

    if revert:
        source_url = entry.get("source_url")
        if not source_url:
            raise AppException(
                status_code=409,
                code="not_normalized",
                message="This image is not normalized — nothing to revert",
            )
        if entry.get("asset_id") is not None:
            staging.purge_asset(int(entry["asset_id"]))
        new_entry: dict[str, Any] = {"url": source_url, "position": position}
    else:
        if entry.get("asset_id") is not None:
            raise AppException(
                status_code=409,
                code="already_normalized",
                message="This image is already normalized",
            )
        config = item.job.config_json or {}
        normalized = normalize_staged_entry(
            db, item, photoroom, url, position, _normalize_options(config)
        )
        if normalized is None:
            raise AppException(
                status_code=502,
                code="normalization_failed",
                message="Photoroom could not process this image",
            )
        new_entry = normalized

    entries[index] = new_entry
    item.staged_images_json = entries
    # Keep the reviewer's partial selection pointing at the same image.
    apply_fields = dict(item.apply_fields_json or {})
    selected = apply_fields.get("image_urls")
    if isinstance(selected, list) and url in selected:
        apply_fields["image_urls"] = [
            new_entry["url"] if u == url else u for u in selected
        ]
        item.apply_fields_json = apply_fields
    db.commit()
    db.refresh(item)
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


def resolve_item_from_url(
    db: Session,
    item: EnrichmentItem,
    url: str,
    *,
    stage: Callable[[EnrichmentItem, str], None],
) -> EnrichmentItem:
    """Re-stage an item from a manually-chosen source page (`stage` fetches +
    scores + stages). Allowed while the item is still under review."""
    if item.status not in ("ready_for_review", "approved"):
        raise AppException(
            status_code=409,
            code="invalid_state",
            message=f"Cannot re-resolve an item in status '{item.status}'",
        )
    try:
        stage(item, url)
    except (LookupError, ValueError, httpx.HTTPError) as exc:
        db.rollback()
        raise AppException(
            status_code=422,
            code="unresolvable_source",
            message=f"Could not resolve from that URL: {exc}",
        ) from exc
    item.error = None
    db.commit()
    db.refresh(item)
    return item


# Statuses a retry (re-generation) is allowed from. `applied` is deliberately
# excluded for now: re-applying would re-send image URLs to Tillin's bulk
# endpoint, which APPENDS (no replace) — needs a dedupe guard first.
_RETRYABLE = ("ready_for_review", "rejected", "failed")


def _reset_item_for_retry(item: EnrichmentItem) -> None:
    """Wipe staged results and requeue the item for a fresh pipeline run."""
    item.status = "pending"
    item.source_url = None
    item.source_method = None
    item.match_score = None
    item.resolution_json = None
    item.staged_title = None
    item.staged_description = None
    item.staged_meta = None
    item.staged_images_json = None
    item.staged_weights_json = None
    item.error = None
    item.attempt_count = 0
    item.started_at = None
    item.finished_at = None


def retry_item(db: Session, item: EnrichmentItem) -> EnrichmentItem:
    """Requeue one item for a full re-generation (resolve + scrape + copy)."""
    if item.status not in _RETRYABLE:
        raise AppException(
            status_code=409,
            code="invalid_state",
            message=f"Cannot retry an item in status '{item.status}'",
        )
    _reset_item_for_retry(item)
    job = db.get(EnrichmentJob, item.job_id)
    if job is not None:
        job.status = "pending"
        job.started_at = None
        job.finished_at = None
    db.commit()
    db.refresh(item)
    return item


def retry_failed_items(db: Session, job: EnrichmentJob) -> int:
    """Requeue every failed/rejected item of a job. Returns how many."""
    targets = [i for i in job.items if i.status in ("failed", "rejected")]
    if not targets:
        raise AppException(
            status_code=409,
            code="invalid_state",
            message="No failed or rejected item to retry in this job",
        )
    for item in targets:
        _reset_item_for_retry(item)
    job.status = "pending"
    job.started_at = None
    job.finished_at = None
    db.commit()
    return len(targets)


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


def apply_item(
    db: Session, item: EnrichmentItem, destination: Destination
) -> EnrichmentItem:
    """Write an approved item's staged fields to the destination, then mark it
    applied. Only `approved` items can be applied (guards double-writes)."""
    if item.status != "approved":
        raise AppException(
            status_code=409,
            code="invalid_state",
            message=f"Cannot apply an item in status '{item.status}'",
        )
    destination.apply(item)
    item.status = "applied"
    item.error = None
    db.commit()
    db.refresh(item)
    return item
