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
    PhotoroomDep,
    SessionDep,
    XanoDep,
    get_current_user,
    require_feature,
)
from app.api.exceptions import AppException
from app.api.schemas import (
    AssetSaveRequest,
    AssetSaveResult,
    FinalizeRequest,
    ImageAssetPublic,
    PendingImagingProducts,
    RenderRequest,
)
from app.api.services.accounts import resolve_account_id
from app.api.services.credits import consume as consume_credits
from app.api.services.credits import credit_grid, require_credits
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
from app.imaging.service import FinalizeOptions, finalize_image
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
    # Repositionner recompose depuis le cutout : le résultat d'une
    # finalisation IA (ombre « cuite », décor…) est écrasé — comportement
    # voulu, une nouvelle finalisation sera facturée (avertissement UI).
    params.pop("finalize", None)
    asset.params_json = params
    db.commit()
    db.refresh(asset)
    return to_public(asset)


@router.post("/assets/{asset_id}/finalize", response_model=ImageAssetPublic)
def finalize_asset(
    asset_id: int,
    body: FinalizeRequest,
    db: SessionDep,
    current_user: CurrentUserDep,
    photoroom: PhotoroomDep,
) -> ImageAssetPublic:
    """Finalisation IA d'une normalisation positionnée (payant, synchrone).

    Un appel Photoroom /v2/edit combine toutes les options demandées (ombre,
    décor IA, défroissage, upscale, beautifier, recoloration) = UN débit
    image_finalize. L'image envoyée est la recomposition RGBA transparente du
    positionnement courant : Photoroom pose l'ombre sur l'alpha puis remplit
    le fond (couleur actuelle, ou décor généré). Un re-render local ultérieur
    efface la finalisation (recompose depuis le cutout).
    """
    account_id = resolve_account_id(db, current_user)
    asset = _renderable_asset(db, account_id, asset_id)
    if not body.has_active_option():
        raise AppException(
            status_code=422,
            code="nothing_to_finalize",
            message="Sélectionnez au moins une retouche à appliquer",
        )
    require_credits(db, account_id, credit_grid(db, account_id)["image_finalize"])

    base_entry = file_by_role(asset, "cutout") or file_by_role(asset, "source")
    if base_entry is None:
        raise AppException(
            status_code=409,
            code="staging_expired",
            message="No staged cutout/source to finalize from",
        )
    try:
        base = staging.load(str(base_entry["path"]))
    except (FileNotFoundError, ValueError):
        raise AppException(
            status_code=409,
            code="staging_expired",
            message="The staged files are no longer available",
        )
    has_cutout = base_entry.get("role") == "cutout"

    # Recompose le positionnement COURANT (options + render stockés), en RGBA
    # transparent quand le cutout existe — Photoroom remplit le fond.
    params = dict(asset.params_json or {})
    stored: dict[str, Any] = dict(params.get("options") or {})
    render: dict[str, Any] = dict(params.get("render") or {})
    crop = render.get("crop")
    composed = compose(
        base,
        has_alpha=has_cutout,
        bg_color=str(stored.get("bg_color", "FFFFFF")),
        ratio=str(stored.get("ratio", "4:5")),
        center=bool(stored.get("center", True)),
        margin_pct=float(stored.get("margin_percent", 0.0)) / 100,
        offset_x=int(render.get("offset_x") or 0),
        offset_y=int(render.get("offset_y") or 0),
        scale=float(render.get("scale") or 1.0),
        fmt="png",
        quality=100,
        max_kb=None,
        crop_box=(
            (crop["x"], crop["y"], crop["width"], crop["height"])
            if isinstance(crop, dict)
            else None
        ),
        transparent_bg=has_cutout,
    )

    options = FinalizeOptions(
        shadow_mode=body.shadow_mode,
        shadow_intensity=body.shadow_intensity,
        # Le fond actuel est ré-appliqué par Photoroom autour de l'ombre —
        # sauf décor IA demandé, qui prime.
        background_color=str(stored.get("bg_color", "FFFFFF")),
        background_prompt=body.background_prompt,
        ironing=body.ironing,
        upscale_factor=body.upscale_factor,
        beautify=body.beautify,
        recolor_prompt=body.recolor_prompt,
        remove_background=not has_cutout,
        output_format=str(stored.get("format", "webp")).replace("jpg", "jpeg"),
    )
    result = finalize_image(
        composed.data,
        options=options,
        photoroom=photoroom,
        db=db,
        account_id=account_id,
    )

    output_path = staging.store(asset.id, 0, result.data, result.format)
    output_entry = {
        "role": "output",
        "path": output_path,
        "bytes": len(result.data),
        "width": result.width,
        "height": result.height,
        "format": result.format,
        "index": 0,
    }
    asset.staged_paths_json = [output_path]
    asset.staged_files_json = [
        entry
        for entry in (asset.staged_files_json or [])
        if entry.get("role") != "output"
    ] + [output_entry]
    params["finalize"] = {
        "options": body.model_dump(),
        "trace": result.trace,
    }
    params["render_rev"] = int(params.get("render_rev") or 0) + 1
    asset.params_json = params
    consume_credits(
        db,
        account_id=account_id,
        action="image_finalize",
        quantity=1,
        asset_id=asset.id,
    )
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
