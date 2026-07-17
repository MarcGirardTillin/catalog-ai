"""Enrichment item routes: detail, staged edits, review decisions, apply."""

from fastapi import APIRouter, BackgroundTasks, Depends

from app.api.deps import (
    CurrentUserDep,
    JobRunnerDep,
    PhotoroomDep,
    PipelineDep,
    SessionDep,
    XanoDep,
    require_feature,
)
from app.api.exceptions import AppException
from app.api.schemas import Product
from app.api.schemas.enrichment import (
    ItemImageNormalizeRequest,
    ItemPatchRequest,
    ItemPublic,
    ItemResolveRequest,
    PagePreview,
)
from app.api.services.accounts import resolve_account_id
from app.api.services.credits import credit_grid, require_credits
from app.api.services.enrichment import (
    apply_item,
    generate_item_copy,
    get_item,
    normalize_item_image,
    resolve_item_from_url,
    retry_item,
    review_item,
    update_staged_fields,
)
from app.destinations.xano_tillin import XanoTillinDestination
from app.sources.preview import fetch_page_preview

# Review = module « Enrichissement » (la normalisation d'images du review
# en fait partie : c'est le flux d'enrichissement, pas le studio).
router = APIRouter(
    prefix="/items",
    tags=["items"],
    dependencies=[Depends(require_feature("feature_enrich"))],
)


@router.get("/{item_id}", response_model=ItemPublic)
def read_item(item_id: int, db: SessionDep, current_user: CurrentUserDep) -> ItemPublic:
    account_id = resolve_account_id(db, current_user)
    item = get_item(db, account_id=account_id, item_id=item_id)
    return ItemPublic.model_validate(item, from_attributes=True)


@router.get("/{item_id}/product", response_model=Product)
def read_item_product(
    item_id: int, db: SessionDep, current_user: CurrentUserDep, xano: XanoDep
) -> Product:
    """Fetch the item's current Tillin product (before/after review context)."""
    account_id = resolve_account_id(db, current_user)
    item = get_item(db, account_id=account_id, item_id=item_id)
    product = xano.get_product(item.tillin_product_id)
    if product is None:
        raise AppException(
            status_code=404,
            code="not_found",
            message=f"Product {item.tillin_product_id} not found in Tillin",
        )
    return product


@router.post("/{item_id}/resolve", response_model=ItemPublic)
def resolve_item_route(
    item_id: int,
    payload: ItemResolveRequest,
    db: SessionDep,
    current_user: CurrentUserDep,
    pipeline: PipelineDep,
) -> ItemPublic:
    """Manually resolve an item from a chosen source page and re-stage it."""
    account_id = resolve_account_id(db, current_user)
    item = get_item(db, account_id=account_id, item_id=item_id)
    item = resolve_item_from_url(
        db, item, payload.source_url, stage=pipeline.stage_from_url
    )
    return ItemPublic.model_validate(item, from_attributes=True)


@router.get("/{item_id}/page-preview", response_model=PagePreview)
def page_preview_route(
    item_id: int,
    url: str,
    db: SessionDep,
    current_user: CurrentUserDep,
) -> PagePreview:
    """Thumbnail (og:image) of one of the item's resolution pages.

    Best-effort : image_url absente quand la page ne publie pas de visuel de
    partage ou ne répond pas. L'URL demandée doit être la page source de
    l'item ou l'un de ses candidats — jamais une URL arbitraire (anti-SSRF).
    """
    account_id = resolve_account_id(db, current_user)
    item = get_item(db, account_id=account_id, item_id=item_id)
    allowed = {item.source_url} | {
        str(candidate.get("url"))
        for candidate in (item.resolution_json or {}).get("candidates") or []
        if isinstance(candidate, dict)
    }
    if url not in allowed:
        raise AppException(
            status_code=422,
            code="unknown_page",
            message="URL is not one of this item's resolution pages",
        )
    return PagePreview(url=url, image_url=fetch_page_preview(url))


@router.post("/{item_id}/generate-copy", response_model=ItemPublic)
def generate_item_copy_route(
    item_id: int,
    db: SessionDep,
    current_user: CurrentUserDep,
    pipeline: PipelineDep,
) -> ItemPublic:
    """Generate the copy from catalog data alone (source left unresolved).

    The batch withholds the description when no source page cleared the
    confidence gate; the reviewer can either confirm a source (resolve) or
    ignore the candidates and ask for a catalog-only generation here. Claude
    usage is metered as usual; the item's enrichment credit was already
    consumed at queue time — no extra debit."""
    account_id = resolve_account_id(db, current_user)
    item = get_item(db, account_id=account_id, item_id=item_id)
    item = generate_item_copy(db, item, stage=pipeline.stage_copy_only)
    return ItemPublic.model_validate(item, from_attributes=True)


@router.post("/{item_id}/retry", response_model=ItemPublic)
def retry_item_route(
    item_id: int,
    db: SessionDep,
    current_user: CurrentUserDep,
    background: BackgroundTasks,
    run_job: JobRunnerDep,
) -> ItemPublic:
    """Requeue one item for a full re-generation and kick the worker."""
    account_id = resolve_account_id(db, current_user)
    item = get_item(db, account_id=account_id, item_id=item_id)
    item = retry_item(db, item)
    background.add_task(run_job, item.job_id)
    return ItemPublic.model_validate(item, from_attributes=True)


@router.patch("/{item_id}", response_model=ItemPublic)
def patch_item(
    item_id: int,
    payload: ItemPatchRequest,
    db: SessionDep,
    current_user: CurrentUserDep,
) -> ItemPublic:
    account_id = resolve_account_id(db, current_user)
    item = get_item(db, account_id=account_id, item_id=item_id)
    item = update_staged_fields(db, item, payload.model_dump(exclude_unset=True))
    return ItemPublic.model_validate(item, from_attributes=True)


@router.post(
    "/{item_id}/images/normalize",
    response_model=ItemPublic,
    # Normaliser une image (détourage Photoroom) = module Studio, même
    # depuis le review d'enrichissement : c'est le traitement payant qui est
    # vendu à part, pas le flux dans lequel il est déclenché (décision Marc
    # 2026-07-16 — le review restait un contournement du blocage studio).
    dependencies=[Depends(require_feature("feature_studio"))],
)
def normalize_item_image_route(
    item_id: int,
    payload: ItemImageNormalizeRequest,
    db: SessionDep,
    current_user: CurrentUserDep,
    photoroom: PhotoroomDep,
) -> ItemPublic:
    """Normalize (or revert) one staged image, chosen by the reviewer.

    The batch stages original source images; each one is normalized on demand
    here (Photoroom, metered on the item's job). The Photoroom dependency
    resolves first: missing key = clean 503, nothing written.
    """
    account_id = resolve_account_id(db, current_user)
    if not payload.revert:
        require_credits(db, account_id, credit_grid(db, account_id)["image_process"])
    item = get_item(db, account_id=account_id, item_id=item_id)
    item = normalize_item_image(
        db, item, photoroom, url=payload.url, revert=payload.revert
    )
    return ItemPublic.model_validate(item, from_attributes=True)


@router.post("/{item_id}/approve", response_model=ItemPublic)
def approve_item(
    item_id: int, db: SessionDep, current_user: CurrentUserDep
) -> ItemPublic:
    account_id = resolve_account_id(db, current_user)
    item = get_item(db, account_id=account_id, item_id=item_id)
    item = review_item(db, item, "approved")
    return ItemPublic.model_validate(item, from_attributes=True)


@router.post("/{item_id}/reject", response_model=ItemPublic)
def reject_item(
    item_id: int, db: SessionDep, current_user: CurrentUserDep
) -> ItemPublic:
    account_id = resolve_account_id(db, current_user)
    item = get_item(db, account_id=account_id, item_id=item_id)
    item = review_item(db, item, "rejected")
    return ItemPublic.model_validate(item, from_attributes=True)


@router.post("/{item_id}/apply", response_model=ItemPublic)
def apply_item_route(
    item_id: int, db: SessionDep, current_user: CurrentUserDep, xano: XanoDep
) -> ItemPublic:
    """Write an approved item's staged enrichment back to Tillin (Xano)."""
    account_id = resolve_account_id(db, current_user)
    item = get_item(db, account_id=account_id, item_id=item_id)
    item = apply_item(db, item, XanoTillinDestination(xano))
    return ItemPublic.model_validate(item, from_attributes=True)
