"""Imaging asset routes: status/preview of à-la-carte operations + save.

Assets are created by the /products/{id}/images/* routes; this router serves
their status, streams the staged previews (authenticated — staging is local
disk, never exposed statically) and pushes completed results to Tillin (Xano
bulk upload, optional replacement of the original image).
"""

from pathlib import PurePosixPath

from fastapi import APIRouter, Depends, Response

from app.api.deps import CurrentUserDep, SessionDep, XanoDep, get_current_user
from app.api.exceptions import AppException
from app.api.schemas import AssetSaveRequest, AssetSaveResult, ImageAssetPublic
from app.api.services.accounts import resolve_account_id
from app.api.services.imaging import MEDIA_TYPES, get_asset, to_public
from app.imaging import staging

router = APIRouter(
    prefix="/imaging",
    tags=["imaging"],
    dependencies=[Depends(get_current_user)],
)


@router.get("/assets/{asset_id}", response_model=ImageAssetPublic)
def read_asset(
    asset_id: int, db: SessionDep, current_user: CurrentUserDep
) -> ImageAssetPublic:
    """Status + preview URLs of one imaging operation (poll target)."""
    account_id = resolve_account_id(db, current_user)
    return to_public(get_asset(db, account_id=account_id, asset_id=asset_id))


@router.get("/assets/{asset_id}/files/{index}")
def read_asset_file(
    asset_id: int, index: int, db: SessionDep, current_user: CurrentUserDep
) -> Response:
    """Stream one staged preview file (404 when absent or already purged)."""
    account_id = resolve_account_id(db, current_user)
    asset = get_asset(db, account_id=account_id, asset_id=asset_id)
    staged = asset.staged_paths_json or []
    if index < 0 or index >= len(staged):
        raise AppException(
            status_code=404, code="not_found", message="Staged file not found"
        )
    relpath = str(staged[index])
    try:
        data = staging.load(relpath)
    except (FileNotFoundError, ValueError):
        raise AppException(
            status_code=404, code="not_found", message="Staged file not found"
        )
    extension = PurePosixPath(relpath).suffix.lstrip(".").lower()
    media_type = MEDIA_TYPES.get(extension, "application/octet-stream")
    return Response(content=data, media_type=media_type)


@router.post("/assets/{asset_id}/save", response_model=AssetSaveResult)
def save_asset(
    asset_id: int,
    body: AssetSaveRequest,
    db: SessionDep,
    current_user: CurrentUserDep,
    xano: XanoDep,
) -> AssetSaveResult:
    """Push the staged results to Tillin (bulk upload) and purge the staging.

    `replace=true` also deactivates the original `product_image` row when the
    asset knows it (source_product_image_id). Saving twice is a 409.
    """
    account_id = resolve_account_id(db, current_user)
    asset = get_asset(db, account_id=account_id, asset_id=asset_id)
    if asset.status != "completed":
        raise AppException(
            status_code=409,
            code="asset_not_completed",
            message="Only completed assets can be saved",
        )
    if asset.tillin_image_ids_json is not None:
        raise AppException(
            status_code=409,
            code="asset_already_saved",
            message="This asset was already saved to Tillin",
        )
    staged = [str(path) for path in (asset.staged_paths_json or [])]
    parts: list[tuple[str, bytes, str]] = []
    for index, relpath in enumerate(staged):
        try:
            data = staging.load(relpath)
        except (FileNotFoundError, ValueError):
            raise AppException(
                status_code=409,
                code="staging_expired",
                message="The staged files are no longer available",
            )
        extension = PurePosixPath(relpath).suffix.lstrip(".").lower()
        parts.append(
            (
                f"{asset.verb}_{asset.id}_{index}.{extension}",
                data,
                MEDIA_TYPES.get(extension, "application/octet-stream"),
            )
        )
    created = xano.upload_product_images(asset.product_id, parts)
    deactivated = 0
    if body.replace and asset.source_product_image_id is not None:
        xano.deactivate_product_images([asset.source_product_image_id])
        deactivated = 1
    asset.tillin_image_ids_json = [
        image.id for image in created if image.id is not None
    ]
    db.commit()
    staging.purge_asset(asset.id)
    return AssetSaveResult(
        created=len(created), deactivated=deactivated, images=created
    )
