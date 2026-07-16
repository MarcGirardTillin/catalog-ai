"""Imaging asset routes: status/preview of à-la-carte operations + save.

Assets are created by the /products/{id}/images/* routes; this router serves
their status, streams the staged previews (authenticated — staging is local
disk, never exposed statically) and pushes completed results to Tillin (Xano
bulk upload, optional replacement of the original image).
"""

from pathlib import PurePosixPath
from typing import Any

from fastapi import APIRouter, Depends, Response

from app.api.deps import (
    CurrentUserDep,
    SessionDep,
    XanoDep,
    get_current_user,
    require_feature,
)
from app.api.exceptions import AppException
from app.api.schemas import (
    AssetSaveRequest,
    AssetSaveResult,
    ImageAssetPublic,
    PendingImagingProducts,
    RenderRequest,
)
from app.api.services.accounts import resolve_account_id
from app.api.services.imaging import (
    MEDIA_TYPES,
    account_settings,
    file_by_role,
    get_asset,
    list_assets,
    output_files,
    pending_product_ids,
    to_public,
)
from app.imaging import staging
from app.imaging.compose import compose
from app.imaging.naming import build_filename, render_image_filename
from app.models import ImageAsset

# Module « Studio » : offre par compte.
router = APIRouter(
    prefix="/imaging",
    tags=["imaging"],
    dependencies=[
        Depends(get_current_user),
        Depends(require_feature("feature_studio")),
    ],
)


@router.get("/assets", response_model=list[ImageAssetPublic])
def list_imaging_assets(
    db: SessionDep,
    current_user: CurrentUserDep,
    product_id: int | None = None,
    verb: str | None = None,
    pending: bool | None = None,
    month: str | None = None,
) -> list[ImageAssetPublic]:
    """Account-scoped asset listing (studio rehydration + generation history).

    `pending=true` = completed and not yet saved to Tillin nor discarded;
    `month` = YYYY-MM on created_at.
    """
    account_id = resolve_account_id(db, current_user)
    assets = list_assets(
        db,
        account_id=account_id,
        product_id=product_id,
        verb=verb,
        pending=pending,
        month=month,
    )
    return [to_public(asset) for asset in assets]


@router.get("/assets/pending-products", response_model=PendingImagingProducts)
def list_pending_products(
    db: SessionDep, current_user: CurrentUserDep
) -> PendingImagingProducts:
    """Product ids with at least one asset to review (catalog row badge)."""
    account_id = resolve_account_id(db, current_user)
    return PendingImagingProducts(
        product_ids=pending_product_ids(db, account_id=account_id)
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


def _renderable_asset(db: SessionDep, account_id: int, asset_id: int) -> ImageAsset:
    """Load an asset eligible for a local re-render (guards → 409)."""
    asset = get_asset(db, account_id=account_id, asset_id=asset_id)
    if asset.verb != "normalize":
        raise AppException(
            status_code=409,
            code="unsupported_verb",
            message="Only normalize assets can be re-rendered",
        )
    if asset.status != "completed":
        raise AppException(
            status_code=409,
            code="asset_not_completed",
            message="Only completed assets can be re-rendered",
        )
    if asset.tillin_image_ids_json is not None:
        raise AppException(
            status_code=409,
            code="asset_already_saved",
            message="This asset was already saved to Tillin",
        )
    return asset


@router.post("/assets/{asset_id}/render", response_model=ImageAssetPublic)
def render_asset(
    asset_id: int,
    body: RenderRequest,
    db: SessionDep,
    current_user: CurrentUserDep,
) -> ImageAssetPublic:
    """Recompose the output locally (reposition / new options) — no provider.

    Rebuilds from the staged cutout (or the source when the cutout was
    skipped), overwrites the output file and bumps `render_rev` so preview
    URLs bust their caches. Synchronous: pure Pillow, sub-second.
    """
    account_id = resolve_account_id(db, current_user)
    asset = _renderable_asset(db, account_id, asset_id)

    base_entry = file_by_role(asset, "cutout") or file_by_role(asset, "source")
    if base_entry is None:  # legacy asset: nothing staged to recompose from
        raise AppException(
            status_code=409,
            code="staging_expired",
            message="No staged cutout/source to re-render from",
        )
    try:
        base = staging.load(str(base_entry["path"]))
    except (FileNotFoundError, ValueError):
        raise AppException(
            status_code=409,
            code="staging_expired",
            message="The staged files are no longer available",
        )

    # Effective options: the asset's stored ones overridden by the request.
    params = dict(asset.params_json or {})
    stored: dict[str, Any] = dict(params.get("options") or {})
    options = {
        "bg_color": body.bg_color or stored.get("bg_color", "FFFFFF"),
        "ratio": body.ratio or stored.get("ratio", "4:5"),
        "center": body.center
        if body.center is not None
        else bool(stored.get("center", True)),
        # La marge suit l'option de création (les vieux assets sans la clé
        # recomposent bord à bord — la politique par défaut actuelle).
        "margin_percent": float(stored.get("margin_percent", 0.0)),
        "format": body.format or stored.get("format", "webp"),
        "quality": body.quality or int(stored.get("quality", 80)),
        "max_kb": body.max_kb or int(stored.get("max_kb", 300)),
    }
    composed = compose(
        base,
        has_alpha=base_entry.get("role") == "cutout",
        bg_color=str(options["bg_color"]),
        ratio=str(options["ratio"]),
        center=bool(options["center"]),
        margin_pct=float(options["margin_percent"]) / 100,
        offset_x=body.offset_x,
        offset_y=body.offset_y,
        scale=body.scale,
        fmt=str(options["format"]),
        quality=int(options["quality"]),
        max_kb=int(options["max_kb"]),
        crop_box=(
            (body.crop.x, body.crop.y, body.crop.width, body.crop.height)
            if body.crop is not None
            else None
        ),
    )

    output_path = staging.store(asset.id, 0, composed.data, composed.format)
    output_entry = {
        "role": "output",
        "path": output_path,
        "bytes": len(composed.data),
        "width": composed.width,
        "height": composed.height,
        "format": composed.format,
        "index": 0,
    }
    asset.staged_paths_json = [output_path]
    asset.staged_files_json = [
        entry
        for entry in (asset.staged_files_json or [])
        if entry.get("role") != "output"
    ] + [output_entry]
    params["options"] = {**stored, **options}
    params["render"] = {
        "offset_x": body.offset_x,
        "offset_y": body.offset_y,
        "scale": body.scale,
        "crop": body.crop.model_dump() if body.crop is not None else None,
    }
    params["render_rev"] = int(params.get("render_rev") or 0) + 1
    asset.params_json = params
    db.commit()
    db.refresh(asset)
    return to_public(asset)


@router.post("/assets/{asset_id}/discard", response_model=ImageAssetPublic)
def discard_asset(
    asset_id: int, db: SessionDep, current_user: CurrentUserDep
) -> ImageAssetPublic:
    """Écarte un résultat non enregistré : purge le staging, garde la trace.

    La ligne reste (historique des générations) avec status="discarded" ;
    seuls les résultats terminés et non enregistrés peuvent être écartés.
    """
    account_id = resolve_account_id(db, current_user)
    asset = get_asset(db, account_id=account_id, asset_id=asset_id)
    if asset.tillin_image_ids_json is not None:
        raise AppException(
            status_code=409,
            code="asset_already_saved",
            message="This asset was already saved to Tillin",
        )
    if asset.status not in ("completed", "failed"):
        raise AppException(
            status_code=409,
            code="asset_not_completed",
            message="Only finished assets can be discarded",
        )
    asset.status = "discarded"
    db.commit()
    staging.purge_asset(asset.id)
    db.refresh(asset)
    return to_public(asset)


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
    filenames = body.filenames or []
    outputs = output_files(asset)
    # Filename resolution: explicit name > image title template > technical
    # default. The product is fetched once, only when the template is needed.
    template = (account_settings(db, account_id).image_title_template or "").strip()
    template_product = None
    if template and any(
        index >= len(filenames) or not filenames[index] for index in range(len(outputs))
    ):
        template_product = xano.get_product(asset.product_id)
    parts: list[tuple[str, bytes, str]] = []
    for index, entry in enumerate(outputs):
        relpath = str(entry["path"])
        try:
            data = staging.load(relpath)
        except (FileNotFoundError, ValueError):
            raise AppException(
                status_code=409,
                code="staging_expired",
                message="The staged files are no longer available",
            )
        extension = PurePosixPath(relpath).suffix.lstrip(".").lower()
        custom = filenames[index] if index < len(filenames) else None
        default_stem = f"{asset.verb}_{asset.id}_{index}"
        if not custom and template_product is not None:
            try:
                default_stem = (
                    render_image_filename(template_product, index + 1, template)
                    or default_stem
                )
            except ValueError:  # unknown token in a hand-edited template
                pass
        parts.append(
            (
                build_filename(custom, extension, default_stem=default_stem),
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
