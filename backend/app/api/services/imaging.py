"""Imaging asset helpers shared by the /products and /imaging routes."""

import logging
from datetime import UTC, datetime
from typing import Any

from sqlalchemy.orm import Session

from app.api.exceptions import AppException
from app.api.schemas import GenerateModelOptions as GenerateModelOptionsSchema
from app.api.schemas import ImageAssetPublic, StagedFilePublic
from app.api.schemas import NormalizeOptions as NormalizeOptionsSchema
from app.clients.fashn import FashnClient
from app.clients.photoroom import PhotoroomClient
from app.core.db import SessionLocal
from app.imaging import staging
from app.imaging.service import (
    GenerateModelOptions,
    NormalizeOptions,
    NormalizeOutcome,
    generate_model_photo,
    normalize_product_image,
)
from app.models import ImageAsset

logger = logging.getLogger(__name__)

# Preview content types by staged-file extension.
MEDIA_TYPES = {
    "webp": "image/webp",
    "jpg": "image/jpeg",
    "jpeg": "image/jpeg",
    "png": "image/png",
}


def output_files(asset: ImageAsset) -> list[dict[str, Any]]:
    """Staged OUTPUT entries with metadata, ordered by index.

    Legacy assets (pre staged_files_json) synthesize bare entries from
    staged_paths_json so preview/save keep working unchanged.
    """
    entries = [
        entry
        for entry in (asset.staged_files_json or [])
        if isinstance(entry, dict) and entry.get("role") == "output"
    ]
    if entries:
        return sorted(entries, key=lambda entry: int(entry.get("index") or 0))
    return [
        {"role": "output", "path": str(path), "index": index}
        for index, path in enumerate(asset.staged_paths_json or [])
    ]


def file_by_role(asset: ImageAsset, role: str) -> dict[str, Any] | None:
    """First staged entry of a given role (source/cutout), None when absent."""
    for entry in asset.staged_files_json or []:
        if isinstance(entry, dict) and entry.get("role") == role:
            return entry
    return None


def to_public(asset: ImageAsset) -> ImageAssetPublic:
    """Map one ImageAsset row onto its public shape (with preview routes)."""
    outputs = output_files(asset)
    render_rev = int((asset.params_json or {}).get("render_rev") or 0)
    suffix = f"?r={render_rev}" if render_rev else ""
    source_entry = file_by_role(asset, "source")
    return ImageAssetPublic(
        id=asset.id,
        product_id=asset.product_id,
        verb=asset.verb,
        provider=asset.provider,
        model=asset.model,
        seed=asset.seed,
        status=asset.status,
        error=asset.error,
        preview_urls=[
            f"/imaging/assets/{asset.id}/files/{index}{suffix}"
            for index in range(len(outputs))
        ],
        files=[
            StagedFilePublic(
                index=index,
                size_bytes=entry.get("bytes"),
                width=entry.get("width"),
                height=entry.get("height"),
                format=entry.get("format"),
            )
            for index, entry in enumerate(outputs)
        ],
        source_size_bytes=source_entry.get("bytes") if source_entry else None,
        source_width=source_entry.get("width") if source_entry else None,
        source_height=source_entry.get("height") if source_entry else None,
        can_render=(
            asset.verb == "normalize"
            and asset.status == "completed"
            and asset.tillin_image_ids_json is None
            and (file_by_role(asset, "cutout") is not None or source_entry is not None)
        ),
        source_image=asset.source_image,
        source_product_image_id=asset.source_product_image_id,
        created_at=asset.created_at,
        finished_at=asset.finished_at,
    )


def get_asset(db: Session, *, account_id: int, asset_id: int) -> ImageAsset:
    """Load one account-scoped asset, or 404."""
    asset = db.get(ImageAsset, asset_id)
    if asset is None or asset.account_id != account_id:
        raise AppException(
            status_code=404, code="not_found", message="Image asset not found"
        )
    return asset


def to_service_options(options: GenerateModelOptionsSchema) -> GenerateModelOptions:
    """API schema -> service dataclass (keeps the verb API framework-free)."""
    return GenerateModelOptions(
        prompt=options.prompt,
        aspect_ratio=options.aspect_ratio,
        resolution=options.resolution,
        generation_mode=options.generation_mode,
        seed=options.seed,
        num_images=options.num_images,
    )


def to_normalize_service_options(options: NormalizeOptionsSchema) -> NormalizeOptions:
    """API schema -> service dataclass for the normalize verb."""
    return NormalizeOptions(
        remove_bg=options.remove_bg,
        bg_color=options.bg_color,
        ratio=options.ratio,
        center=options.center,
        fmt=options.format,
        quality=options.quality,
        max_kb=options.max_kb,
    )


def stage_normalize_outcome(asset: ImageAsset, outcome: NormalizeOutcome) -> None:
    """Persist a normalize outcome on the asset: files on disk + metadata.

    Output at index 0 (staged_paths_json contract), plus the cutout and the
    source under role stems — they make POST /render possible without a new
    provider call. The caller commits.
    """
    output = outcome.output
    output_path = staging.store(asset.id, 0, output.data, output.format)
    files: list[dict[str, Any]] = [
        {
            "role": "output",
            "path": output_path,
            "bytes": len(output.data),
            "width": output.width,
            "height": output.height,
            "format": output.format,
            "index": 0,
        },
        {
            "role": "source",
            "path": staging.store(
                asset.id, "source", outcome.source.data, outcome.source.format
            ),
            "bytes": len(outcome.source.data),
            "width": outcome.source.width,
            "height": outcome.source.height,
            "format": outcome.source.format,
        },
    ]
    if outcome.cutout is not None:
        files.append(
            {
                "role": "cutout",
                "path": staging.store(asset.id, "cutout", outcome.cutout, "png"),
                "bytes": len(outcome.cutout),
                "format": "png",
            }
        )
    asset.staged_paths_json = [output_path]
    asset.staged_files_json = files
    asset.status = "completed"
    asset.finished_at = datetime.now(UTC)
    asset.params_json = {**(asset.params_json or {}), "trace": output.trace}


def run_normalize(
    asset_id: int,
    image_url: str,
    options: NormalizeOptionsSchema,
    photoroom: PhotoroomClient,
) -> None:
    """BackgroundTask entrypoint of the normalize pipeline (own DB session).

    Same lifecycle as run_generate_model: processing -> verb -> staging ->
    completed, or failed + error. The pipeline takes seconds (download +
    segment + Pillow), hence the 202 pattern.
    """
    db = SessionLocal()
    try:
        asset = db.get(ImageAsset, asset_id)
        if asset is None:  # pragma: no cover - defensive
            logger.warning("image_asset %s vanished before processing", asset_id)
            return
        asset.status = "processing"
        db.commit()
        try:
            outcome = normalize_product_image(
                image_url,
                options=to_normalize_service_options(options),
                photoroom=photoroom,
                db=db,
                account_id=asset.account_id,
            )
            stage_normalize_outcome(asset, outcome)
            db.commit()
        except Exception as exc:
            db.rollback()
            logger.exception("normalize failed for asset %s", asset_id)
            asset = db.get(ImageAsset, asset_id)
            if asset is not None:
                asset.status = "failed"
                asset.error = str(exc)
                asset.finished_at = datetime.now(UTC)
                db.commit()
    finally:
        db.close()


def run_generate_model(
    asset_id: int,
    image_url: str,
    options: GenerateModelOptionsSchema,
    fashn: FashnClient,
) -> None:
    """BackgroundTask entrypoint: run the FASHN verb with its OWN DB session.

    The request session is closed when the background task runs (same reason
    `jobs/runner.py` opens fresh sessions), so this owns its transaction:
    processing -> verb -> staging -> completed, or failed + error.
    """
    db = SessionLocal()
    try:
        asset = db.get(ImageAsset, asset_id)
        if asset is None:  # pragma: no cover - defensive
            logger.warning("image_asset %s vanished before processing", asset_id)
            return
        asset.status = "processing"
        db.commit()
        try:
            results = generate_model_photo(
                image_url,
                options=to_service_options(options),
                fashn=fashn,
                db=db,
                account_id=asset.account_id,
            )
            asset.staged_paths_json = [
                staging.store(asset.id, index, result.data, result.format)
                for index, result in enumerate(results)
            ]
            asset.status = "completed"
            asset.finished_at = datetime.now(UTC)
            if results:
                asset.params_json = {
                    **(asset.params_json or {}),
                    "trace": results[0].trace,
                }
            db.commit()
        except Exception as exc:
            db.rollback()
            logger.exception("generate-model failed for asset %s", asset_id)
            asset = db.get(ImageAsset, asset_id)
            if asset is not None:
                asset.status = "failed"
                asset.error = str(exc)
                asset.finished_at = datetime.now(UTC)
                db.commit()
    finally:
        db.close()
