"""Imaging asset helpers shared by the /products and /imaging routes."""

import logging
from datetime import UTC, datetime

from sqlalchemy.orm import Session

from app.api.exceptions import AppException
from app.api.schemas import GenerateModelOptions as GenerateModelOptionsSchema
from app.api.schemas import ImageAssetPublic
from app.clients.fashn import FashnClient
from app.core.db import SessionLocal
from app.imaging import staging
from app.imaging.service import GenerateModelOptions, generate_model_photo
from app.models import ImageAsset

logger = logging.getLogger(__name__)

# Preview content types by staged-file extension.
MEDIA_TYPES = {
    "webp": "image/webp",
    "jpg": "image/jpeg",
    "jpeg": "image/jpeg",
    "png": "image/png",
}


def to_public(asset: ImageAsset) -> ImageAssetPublic:
    """Map one ImageAsset row onto its public shape (with preview routes)."""
    staged = asset.staged_paths_json or []
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
            f"/imaging/assets/{asset.id}/files/{index}" for index in range(len(staged))
        ],
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
