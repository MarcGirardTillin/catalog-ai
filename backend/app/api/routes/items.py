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
)
from app.api.services.accounts import resolve_account_id
from app.api.services.credits import credit_grid, require_credits
from app.api.services.enrichment import (
    apply_item,
    get_item,
    normalize_item_image,
    resolve_item_from_url,
    retry_item,
    review_item,
    update_staged_fields,
)
from app.destinations.xano_tillin import XanoTillinDestination

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


@router.post("/{item_id}/images/normalize", response_model=ItemPublic)
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
