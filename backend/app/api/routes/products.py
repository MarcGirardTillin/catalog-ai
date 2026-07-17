"""Product selection route — searches the Tillin catalog through Xano.

Backs the CatalogAI selection screen: free-text search + filters over the
Tillin catalog so the user can pick product ids, then build an enrichment job
from that selection. The Xano bearer token never reaches the browser — the
backend proxies the call behind the session cookie.
"""

import logging
from typing import Annotated

from fastapi import APIRouter, BackgroundTasks, Depends, File, Query, UploadFile

from app.api.deps import (
    CurrentUserDep,
    OptionalFashnDep,
    OptionalPhotoroomDep,
    PhotoroomDep,
    SessionDep,
    XanoDep,
    get_current_user,
    require_feature,
)
from app.api.exceptions import AppException
from app.api.schemas import GenerateFlatOptions as GenerateFlatOptionsSchema
from app.api.schemas import (
    GenerateFlatRequest,
    GenerateModelRequest,
    ImageAssetPublic,
    NormalizeRequest,
    PaginatedResponse,
    Product,
    ProductImagesUploadResult,
)
from app.api.schemas import GenerateModelOptions as GenerateModelOptionsSchema
from app.api.services.accounts import resolve_account_id
from app.api.services.credits import credit_grid, require_credits
from app.api.services.imaging import (
    account_settings,
    merged_normalize_options,
    run_generate_flat,
    run_generate_ghost,
    run_generate_model,
    run_generate_virtual_model,
    run_normalize,
    to_flat_service_options,
    to_public,
    to_virtual_model_service_options,
)
from app.clients.base import NotConfiguredError
from app.imaging import service as imaging_service
from app.imaging.uploads import prepare_upload
from app.models import ImageAsset

logger = logging.getLogger(__name__)

# Guardrails for the upload route (a boutique adds a handful of shots at a time).
MAX_UPLOAD_FILES = 20
MAX_UPLOAD_BYTES = 15 * 1024 * 1024  # 15 MB per file

router = APIRouter(
    prefix="/products",
    tags=["products"],
    dependencies=[Depends(get_current_user)],
)


@router.get("", response_model=PaginatedResponse[Product])
def list_products(
    xano: XanoDep,
    search: Annotated[str | None, Query(description="Free-text search")] = None,
    brand: Annotated[int | None, Query(description="Filter by brand id")] = None,
    category: Annotated[int | None, Query(description="Filter by category id")] = None,
    supplier: Annotated[int | None, Query(description="Filter by supplier id")] = None,
    season: Annotated[int | None, Query(description="Filter by season id")] = None,
    tag: Annotated[int | None, Query(description="Filter by tag id")] = None,
    status: Annotated[str | None, Query(description="Filter by status")] = None,
    ecommerce: Annotated[
        int | None,
        Query(
            ge=1,
            le=4,
            description=(
                "Connexion e-commerce (natif Xano) : 1 tous, 2 connectés, "
                "3 partiellement connectés, 4 non connectés"
            ),
        ),
    ] = None,
    page: Annotated[int, Query(ge=1)] = 1,
    per_page: Annotated[int, Query(ge=1, le=100)] = 20,
) -> PaginatedResponse[Product]:
    """Return a page of canonical products matching the search + filters."""
    result = xano.search_products(
        text=search,
        brand=brand,
        category=category,
        supplier=supplier,
        season=season,
        tag=tag,
        status=status,
        ecommerce=ecommerce,
        page=page,
        per_page=per_page,
    )
    total_pages = (result.total + per_page - 1) // per_page if per_page else 0
    return PaginatedResponse(
        items=result.items,
        total=result.total,
        page=page,
        page_size=per_page,
        total_pages=total_pages,
    )


@router.get("/{product_id}", response_model=Product)
def read_product(product_id: int, xano: XanoDep) -> Product:
    """Return one product's full detail from the Tillin catalog."""
    product = xano.get_product(product_id)
    if product is None:
        raise AppException(
            status_code=404, code="not_found", message="Product not found"
        )
    return product


@router.post("/{product_id}/images", response_model=ProductImagesUploadResult)
def upload_product_images(
    product_id: int,
    xano: XanoDep,
    files: Annotated[list[UploadFile], File(description="Image files to upload")],
) -> ProductImagesUploadResult:
    """Upload local/captured images to a product (proxied to Tillin storage).

    The browser posts the raw image bytes here; the backend forwards them to
    Tillin's bulk endpoint (multipart), which imports each into Xano storage and
    appends a `product_image` row. The Xano token never reaches the browser.

    Every file goes through `prepare_upload` first: Tillin silently drops what
    it cannot decode (200 with `images: []`), so the real format is detected
    here, HEIC is converted, and the name always carries the right extension.
    """
    if not files:
        raise AppException(
            status_code=422, code="no_files", message="No image provided"
        )
    if len(files) > MAX_UPLOAD_FILES:
        raise AppException(
            status_code=422,
            code="too_many_files",
            message=f"Too many files (max {MAX_UPLOAD_FILES})",
        )
    parts: list[tuple[str, bytes, str]] = []
    for index, upload in enumerate(files):
        data = upload.file.read()  # sync route -> threadpool; use the sync handle
        if len(data) > MAX_UPLOAD_BYTES:
            raise AppException(
                status_code=422,
                code="file_too_large",
                message=f"{upload.filename or 'file'} exceeds the size limit",
            )
        parts.append(prepare_upload(upload.filename, data, index=index))
    created = xano.upload_product_images(product_id, parts)
    if len(created) < len(parts):
        # Tillin a accepté la requête mais n'a pas créé toutes les images :
        # sans ça l'appelant recevait un 200 « 0 image créée » inexploitable.
        logger.error(
            "Tillin created %d/%d images for product %s (names: %s)",
            len(created),
            len(parts),
            product_id,
            [name for name, _, _ in parts],
        )
        raise AppException(
            status_code=502,
            code="images_rejected",
            message=(
                "Tillin n'a pas enregistré les images envoyées. "
                "Réessayez ; si le problème persiste, contactez le support."
            ),
        )
    return ProductImagesUploadResult(created=len(created), images=created)


@router.post(
    "/{product_id}/images/normalize",
    response_model=ImageAssetPublic,
    status_code=202,
    # Traitement d'image = module Studio (l'upload, lui, reste du socle).
    dependencies=[Depends(require_feature("feature_studio"))],
)
def normalize_image(
    product_id: int,
    body: NormalizeRequest,
    db: SessionDep,
    current_user: CurrentUserDep,
    photoroom: PhotoroomDep,
    background: BackgroundTasks,
) -> ImageAssetPublic:
    """Deterministic pipeline, async (download + segment + Pillow ≈ seconds).

    Same 202 + BackgroundTask + polling contract as generate-model — the
    studio launches several normalizations in parallel. The Photoroom
    dependency resolves BEFORE any write: a missing key is a clean 503 with
    no zombie asset.
    """
    account_id = resolve_account_id(db, current_user)
    require_credits(db, account_id, credit_grid(db, account_id)["image_process"])
    # Account imaging defaults, overridden by the explicitly-sent fields only.
    options = merged_normalize_options(db, account_id, body.options)
    asset = ImageAsset(
        account_id=account_id,
        product_id=product_id,
        verb="normalize",
        provider="photoroom" if options.remove_bg else "local",
        model=imaging_service.PHOTOROOM_SEGMENT_MODEL if options.remove_bg else None,
        status="pending",
        source_image=body.image_url,
        source_product_image_id=body.product_image_id,
        params_json={"options": options.model_dump()},
    )
    db.add(asset)
    db.commit()
    db.refresh(asset)
    background.add_task(run_normalize, asset.id, body.image_url, options, photoroom)
    return to_public(asset)


@router.post(
    "/{product_id}/images/generate-model",
    response_model=ImageAssetPublic,
    status_code=202,
    dependencies=[Depends(require_feature("feature_studio"))],
)
def generate_model_image(
    product_id: int,
    body: GenerateModelRequest,
    db: SessionDep,
    current_user: CurrentUserDep,
    fashn: OptionalFashnDep,
    photoroom: OptionalPhotoroomDep,
    background: BackgroundTasks,
) -> ImageAssetPublic:
    """Generative pipeline, 202 + asset id (FASHN 10-55 s, Photoroom 5-60 s).

    Deux moteurs au choix par appel (défaut = réglage du compte) : FASHN
    product-to-model (historique) ou Photoroom Virtual Model (presets natifs
    mannequin/décor/pose, multi-vues). Les deux clients sont résolus en
    variante optionnelle : seule la clé du moteur CHOISI est requise (503
    propre AVANT toute écriture sinon).
    """
    account_id = resolve_account_id(db, current_user)
    stored = account_settings(db, account_id)
    options = body.options or GenerateModelOptionsSchema()
    engine = options.engine or stored.imaging_generation_engine

    if engine == "photoroom":
        if photoroom is None:
            raise NotConfiguredError("photoroom")
        # Photoroom rend UNE image par appel (pas de num_images/seed).
        require_credits(db, account_id, credit_grid(db, account_id)["image_generate"])
        vm_options = to_virtual_model_service_options(
            options, stored, body.additional_image_urls
        )
        asset = ImageAsset(
            account_id=account_id,
            product_id=product_id,
            verb="generate_model",
            provider="photoroom",
            model=imaging_service.PHOTOROOM_EDIT_MODEL,
            status="pending",
            source_image=body.image_url,
            source_product_image_id=body.product_image_id,
            params_json={"options": {**options.model_dump(), "engine": "photoroom"}},
        )
        db.add(asset)
        db.commit()
        db.refresh(asset)
        background.add_task(
            run_generate_virtual_model, asset.id, body.image_url, vm_options, photoroom
        )
        return to_public(asset)

    if fashn is None:
        raise NotConfiguredError("fashn")
    require_credits(
        db,
        account_id,
        credit_grid(db, account_id)["image_generate"] * options.num_images,
    )
    if options.prompt is None:
        # Instruction composée : champs explicites de la requête, repli sur
        # les réglages de génération du compte champ par champ.
        options = options.model_copy(
            update={
                "prompt": imaging_service.build_generation_prompt(
                    options.framing or stored.imaging_generation_framing,
                    options.scene or stored.imaging_generation_scene,
                    options.instructions
                    if options.instructions is not None
                    else stored.imaging_generation_instructions,
                    pose=options.pose or stored.imaging_generation_pose,
                )
            }
        )
    asset = ImageAsset(
        account_id=account_id,
        product_id=product_id,
        verb="generate_model",
        provider="fashn",
        model=imaging_service.FASHN_PRODUCT_TO_MODEL,
        seed=options.seed,
        status="pending",
        source_image=body.image_url,
        source_product_image_id=body.product_image_id,
        params_json={"options": options.model_dump()},
    )
    db.add(asset)
    db.commit()
    db.refresh(asset)
    background.add_task(run_generate_model, asset.id, body.image_url, options, fashn)
    return to_public(asset)


@router.post(
    "/{product_id}/images/generate-flat",
    response_model=ImageAssetPublic,
    status_code=202,
    dependencies=[Depends(require_feature("feature_studio"))],
)
def generate_flat_image(
    product_id: int,
    body: GenerateFlatRequest,
    db: SessionDep,
    current_user: CurrentUserDep,
    photoroom: PhotoroomDep,
    background: BackgroundTasks,
) -> ImageAssetPublic:
    """Mise à plat stylisée (Photoroom flat lay) — 202 + polling, comme les
    autres générations. Un appel = une image = un débit image_generate."""
    account_id = resolve_account_id(db, current_user)
    require_credits(db, account_id, credit_grid(db, account_id)["image_generate"])
    options = to_flat_service_options(body.options)
    asset = ImageAsset(
        account_id=account_id,
        product_id=product_id,
        verb="generate_flat",
        provider="photoroom",
        model=imaging_service.PHOTOROOM_EDIT_MODEL,
        status="pending",
        source_image=body.image_url,
        source_product_image_id=body.product_image_id,
        params_json={
            "options": (body.options or GenerateFlatOptionsSchema()).model_dump()
        },
    )
    db.add(asset)
    db.commit()
    db.refresh(asset)
    background.add_task(run_generate_flat, asset.id, body.image_url, options, photoroom)
    return to_public(asset)


@router.post(
    "/{product_id}/images/generate-ghost",
    response_model=ImageAssetPublic,
    status_code=202,
    dependencies=[Depends(require_feature("feature_studio"))],
)
def generate_ghost_image(
    product_id: int,
    body: GenerateFlatRequest,
    db: SessionDep,
    current_user: CurrentUserDep,
    photoroom: PhotoroomDep,
    background: BackgroundTasks,
) -> ImageAssetPublic:
    """Mannequin invisible (Photoroom ghost mannequin) — efface le mannequin
    d'une photo portée. Un appel = une image = un débit image_generate."""
    account_id = resolve_account_id(db, current_user)
    require_credits(db, account_id, credit_grid(db, account_id)["image_generate"])
    options = to_flat_service_options(body.options)
    asset = ImageAsset(
        account_id=account_id,
        product_id=product_id,
        verb="generate_ghost",
        provider="photoroom",
        model=imaging_service.PHOTOROOM_EDIT_MODEL,
        status="pending",
        source_image=body.image_url,
        source_product_image_id=body.product_image_id,
        params_json={
            "options": (body.options or GenerateFlatOptionsSchema()).model_dump()
        },
    )
    db.add(asset)
    db.commit()
    db.refresh(asset)
    background.add_task(
        run_generate_ghost, asset.id, body.image_url, options, photoroom
    )
    return to_public(asset)
