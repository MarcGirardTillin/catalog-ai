"""Enrichment item routes: detail, staged edits, review decisions, apply."""

from fastapi import APIRouter

from app.api.deps import CurrentUserDep, SessionDep, XanoDep
from app.api.schemas.enrichment import ItemPatchRequest, ItemPublic
from app.api.services.accounts import resolve_account_id
from app.api.services.enrichment import (
    apply_item,
    get_item,
    review_item,
    update_staged_fields,
)
from app.destinations.xano_tillin import XanoTillinDestination

router = APIRouter(prefix="/items", tags=["items"])


@router.get("/{item_id}", response_model=ItemPublic)
def read_item(item_id: int, db: SessionDep, current_user: CurrentUserDep) -> ItemPublic:
    account_id = resolve_account_id(db, current_user)
    item = get_item(db, account_id=account_id, item_id=item_id)
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
