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
    OptionalXanoDep,
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
    ProductImagePositionsRequest,
    ProductImagesUploadResult,
    RecolorRequest,
    SwapModelRequest,
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
    run_recolor,
    run_swap_model,
    to_flat_service_options,
    to_public,
    to_virtual_model_service_options,
)
from app.clients.base import NotConfiguredError
from app.clients.xano import XanoClient
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


@router.put("/{product_id}/images/positions", response_model=Product)
def reorder_product_images(
    product_id: int, xano: XanoDep, payload: ProductImagePositionsRequest
) -> Product:
    """Réordonne la galerie Tillin du produit.

    La liste ORDONNÉE d'ids d'images devient les positions 1..n (endpoint
    Xano `PUT /product_image/positions`). Les ids sont vérifiés contre la
    galerie actuelle — un id inconnu (image supprimée entre-temps) est un
    422 plutôt qu'une écriture partielle. Renvoie le produit relu.
    """
    product = xano.get_product(product_id)
    if product is None:
        raise AppException(
            status_code=404, code="not_found", message="Product not found"
        )
    known = {image.id for image in product.images if image.id is not None}
    unknown = [i for i in payload.product_image_ids if i not in known]
    if unknown:
        raise AppException(
            status_code=422,
            code="unknown_image",
            message="La galerie a changé — rechargez le produit avant de réordonner",
        )
    xano.set_product_image_positions(
        [
            (image_id, position)
            for position, image_id in enumerate(payload.product_image_ids, start=1)
        ]
    )
    updated = xano.get_product(product_id)
    return updated if updated is not None else product


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
    xano: OptionalXanoDep,
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

    # Genre du mannequin : choix explicite > défaut du compte > department du
    # produit Tillin (Homme/Femme ; Unisex/inconnu = libre).
    gender: str | None = (
        options.gender
        if options.gender and options.gender != "auto"
        else stored.imaging_generation_gender
    )
    if gender == "auto":
        gender = _product_gender(xano, product_id)

    if engine == "photoroom":
        if photoroom is None:
            raise NotConfiguredError("photoroom")
        # Photoroom rend UNE image par appel (pas de num_images/seed).
        require_credits(db, account_id, credit_grid(db, account_id)["image_generate"])
        vm_options = to_virtual_model_service_options(
            options, stored, body.additional_image_urls, gender=gender
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
                    dimensions=options.product_dimensions,
                    gender=gender,
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
    "/{product_id}/images/swap-model",
    response_model=ImageAssetPublic,
    status_code=202,
)
def swap_model_image(
    product_id: int,
    body: SwapModelRequest,
    db: SessionDep,
    current_user: CurrentUserDep,
    fashn: OptionalFashnDep,
    background: BackgroundTasks,
) -> ImageAssetPublic:
    """« Remplacer le mannequin » (FASHN model-swap, validé Marc 2026-07-31).

    Change l'identité du mannequin (visage, carnation, cheveux) en conservant
    la tenue. Visage de la bibliothèque du compte envoyé en data URI (jamais
    d'URL publique). Un appel = une image = un débit image_generate.
    """
    import base64 as _base64

    from app.imaging import staging as _staging
    from app.models import FaceReference

    account_id = resolve_account_id(db, current_user)
    if fashn is None:
        raise NotConfiguredError("fashn")
    require_credits(db, account_id, credit_grid(db, account_id)["image_generate"])
    face_data_uri: str | None = None
    face_name: str | None = None
    if body.face_id is not None:
        face = db.get(FaceReference, body.face_id)
        if face is None or face.account_id != account_id:
            raise AppException(
                status_code=404, code="not_found", message="Visage introuvable"
            )
        try:
            data = _staging.load(face.file_path)
        except (FileNotFoundError, ValueError) as exc:
            raise AppException(
                status_code=409,
                code="file_missing",
                message="Fichier du visage introuvable — re-téléversez-le",
            ) from exc
        extension = face.file_path.rsplit(".", 1)[-1]
        media = {"jpg": "image/jpeg", "png": "image/png", "webp": "image/webp"}.get(
            extension, "image/jpeg"
        )
        face_data_uri = f"data:{media};base64," + _base64.standard_b64encode(
            data
        ).decode("ascii")
        face_name = face.name
    asset = ImageAsset(
        account_id=account_id,
        product_id=product_id,
        verb="swap_model",
        provider="fashn",
        model=imaging_service.FASHN_MODEL_SWAP,
        status="pending",
        source_image=body.image_url,
        source_product_image_id=body.product_image_id,
        params_json={
            "options": {
                "face_id": body.face_id,
                "face_name": face_name,
                "face_reference_mode": body.face_reference_mode,
                "prompt": body.prompt,
            }
        },
    )
    db.add(asset)
    db.commit()
    db.refresh(asset)
    background.add_task(
        run_swap_model,
        asset.id,
        body.image_url,
        face_data_uri,
        body.face_reference_mode,
        body.prompt,
        fashn,
    )
    return to_public(asset)


@router.post(
    "/{product_id}/images/recolor",
    response_model=ImageAssetPublic,
    status_code=202,
    dependencies=[Depends(require_feature("feature_studio"))],
)
def recolor_image(
    product_id: int,
    body: RecolorRequest,
    db: SessionDep,
    current_user: CurrentUserDep,
    fashn: OptionalFashnDep,
    xano: OptionalXanoDep,
    background: BackgroundTasks,
) -> ImageAssetPublic:
    """« Changer la couleur » (FASHN edit, validé Marc 2026-08-21).

    Change la couleur du vêtement en préservant texture/coupe/lumière. La
    cible vient du picker (`color`) ou d'une image de référence
    (`reference_image_url`, envoyée en `image_context`). Débit image_generate
    × qualité choisie (1k/2k/4k)."""
    account_id = resolve_account_id(db, current_user)
    if fashn is None:
        raise NotConfiguredError("fashn")
    if not (body.color or "").strip() and not body.reference_image_url:
        raise AppException(
            status_code=422,
            code="missing_color",
            message="Choisissez une couleur ou une image de référence",
        )
    require_credits(
        db,
        account_id,
        credit_grid(db, account_id)["image_generate"]
        * imaging_service.RESOLUTION_CREDIT_UNITS.get(body.resolution, 1),
    )
    prompt = imaging_service.build_recolor_prompt(
        body.color,
        _product_garment(xano, product_id),
        body.instructions,
        has_reference=body.reference_image_url is not None,
    )
    asset = ImageAsset(
        account_id=account_id,
        product_id=product_id,
        verb="recolor",
        provider="fashn",
        model=imaging_service.FASHN_EDIT,
        status="pending",
        source_image=body.image_url,
        source_product_image_id=body.product_image_id,
        params_json={
            "options": {
                "color": body.color,
                "reference_image_url": body.reference_image_url,
                "instructions": body.instructions,
                "resolution": body.resolution,
            }
        },
    )
    db.add(asset)
    db.commit()
    db.refresh(asset)
    background.add_task(
        run_recolor,
        asset.id,
        body.image_url,
        prompt,
        body.reference_image_url,
        body.resolution,
        fashn,
    )
    return to_public(asset)


def _product_garment(xano: XanoClient | None, product_id: int) -> str | None:
    """Catégorie du produit (cible du flat lay/ghost) — best-effort."""
    if xano is None:
        return None
    try:
        product = xano.get_product(product_id)
    except Exception:  # noqa: BLE001 — enrichissement du prompt, jamais bloquant
        return None
    return product.category if product else None


_DEPARTMENT_GENDERS = {"homme": "male", "femme": "female"}


def _product_gender(xano: XanoClient | None, product_id: int) -> str | None:
    """Genre du mannequin déduit du department Tillin — best-effort."""
    if xano is None:
        return None
    try:
        product = xano.get_product(product_id)
    except Exception:  # noqa: BLE001 — enrichissement du prompt, jamais bloquant
        return None
    department = (product.department or "") if product else ""
    return _DEPARTMENT_GENDERS.get(department.strip().lower())


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
    xano: OptionalXanoDep,
    background: BackgroundTasks,
) -> ImageAssetPublic:
    """Mise à plat stylisée (Photoroom flat lay) — 202 + polling, comme les
    autres générations. Débit image_generate × qualité choisie (1k/2k/4k)."""
    account_id = resolve_account_id(db, current_user)
    resolution = (body.options or GenerateFlatOptionsSchema()).resolution
    require_credits(
        db,
        account_id,
        credit_grid(db, account_id)["image_generate"]
        * imaging_service.RESOLUTION_CREDIT_UNITS.get(resolution, 1),
    )
    stored = account_settings(db, account_id)
    options = to_flat_service_options(
        body.options,
        background_color=stored.imaging_bg_color,
        garment=_product_garment(xano, product_id),
    )
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
    xano: OptionalXanoDep,
    background: BackgroundTasks,
) -> ImageAssetPublic:
    """Mannequin invisible (Photoroom ghost mannequin) — efface le mannequin
    d'une photo portée. Débit image_generate × qualité choisie (1k/2k/4k)."""
    account_id = resolve_account_id(db, current_user)
    resolution = (body.options or GenerateFlatOptionsSchema()).resolution
    require_credits(
        db,
        account_id,
        credit_grid(db, account_id)["image_generate"]
        * imaging_service.RESOLUTION_CREDIT_UNITS.get(resolution, 1),
    )
    stored = account_settings(db, account_id)
    options = to_flat_service_options(
        body.options,
        background_color=stored.imaging_bg_color,
        garment=_product_garment(xano, product_id),
    )
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
