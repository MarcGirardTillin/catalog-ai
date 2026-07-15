"""Product selection route — searches the Tillin catalog through Xano.

Backs the CatalogAI selection screen: free-text search + filters over the
Tillin catalog so the user can pick product ids, then build an enrichment job
from that selection. The Xano bearer token never reaches the browser — the
backend proxies the call behind the session cookie.
"""

from typing import Annotated

from fastapi import APIRouter, BackgroundTasks, Depends, File, Query, UploadFile

from app.api.deps import (
    CurrentUserDep,
    FashnDep,
    PhotoroomDep,
    SessionDep,
    XanoDep,
    get_current_user,
)
from app.api.exceptions import AppException
from app.api.schemas import GenerateModelOptions as GenerateModelOptionsSchema
from app.api.schemas import (
    GenerateModelRequest,
    ImageAssetPublic,
    NormalizeRequest,
    PaginatedResponse,
    Product,
    ProductImagesUploadResult,
)
from app.api.services.accounts import resolve_account_id
from app.api.services.credits import credit_grid, require_credits
from app.api.services.imaging import (
    account_settings,
    merged_normalize_options,
    run_generate_model,
    run_normalize,
    to_public,
)
from app.imaging import service as imaging_service
from app.models import ImageAsset

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
    for upload in files:
        data = upload.file.read()  # sync route -> threadpool; use the sync handle
        if len(data) > MAX_UPLOAD_BYTES:
            raise AppException(
                status_code=422,
                code="file_too_large",
                message=f"{upload.filename or 'file'} exceeds the size limit",
            )
        parts.append(
            (
                upload.filename or "image.jpg",
                data,
                upload.content_type or "application/octet-stream",
            )
        )
    created = xano.upload_product_images(product_id, parts)
    return ProductImagesUploadResult(created=len(created), images=created)


@router.post(
    "/{product_id}/images/normalize",
    response_model=ImageAssetPublic,
    status_code=202,
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
)
def generate_model_image(
    product_id: int,
    body: GenerateModelRequest,
    db: SessionDep,
    current_user: CurrentUserDep,
    fashn: FashnDep,
    background: BackgroundTasks,
) -> ImageAssetPublic:
    """Generative pipeline, 202 + asset id (FASHN takes 10-55 s).

    The FASHN dependency resolves BEFORE any row is written: a missing key is
    a clean 503 with no zombie asset. The BackgroundTask polls FASHN, downloads
    the outputs to staging and settles the asset with its own DB session.
    """
    account_id = resolve_account_id(db, current_user)
    options = body.options or GenerateModelOptionsSchema()
    require_credits(
        db,
        account_id,
        credit_grid(db, account_id)["image_generate"] * options.num_images,
    )
    if options.prompt is None:
        # Instruction composée : champs explicites de la requête, repli sur
        # les réglages de génération du compte champ par champ.
        stored = account_settings(db, account_id)
        options = options.model_copy(
            update={
                "prompt": imaging_service.build_generation_prompt(
                    options.framing or stored.imaging_generation_framing,
                    options.scene or stored.imaging_generation_scene,
                    options.instructions
                    if options.instructions is not None
                    else stored.imaging_generation_instructions,
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
