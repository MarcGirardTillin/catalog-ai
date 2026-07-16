"""Import profile CRUD — per-account supplier conventions (rule shapes are
frozen in `app.api.schemas.import_profiles.ImportProfileConfig`).

`supplier_match` is stored lowercased/stripped so it can be compared against
the extracted document supplier for auto-suggestion.
"""

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import CurrentUserDep, SessionDep, require_feature
from app.api.exceptions import AppException
from app.api.schemas.import_profiles import (
    ImportProfileConfig,
    ImportProfileCreate,
    ImportProfilePublic,
    ImportProfilesBulkUpdate,
    ImportProfileUpdate,
)
from app.api.services.accounts import resolve_account_id
from app.models import ImportProfile

router = APIRouter(
    prefix="/import-profiles",
    tags=["import-profiles"],
    dependencies=[Depends(require_feature("feature_import"))],
)


def _to_public(profile: ImportProfile) -> ImportProfilePublic:
    return ImportProfilePublic(
        id=profile.id,
        name=profile.name,
        supplier_match=profile.supplier_match,
        config=ImportProfileConfig.model_validate(profile.config_json or {}),
        created_at=profile.created_at,
        updated_at=profile.updated_at,
    )


def _get_profile(db: Session, *, account_id: int, profile_id: int) -> ImportProfile:
    profile = db.get(ImportProfile, profile_id)
    if profile is None or profile.account_id != account_id:
        raise AppException(
            status_code=404, code="not_found", message="Import profile not found"
        )
    return profile


@router.get("", response_model=list[ImportProfilePublic])
def list_import_profiles(
    db: SessionDep, current_user: CurrentUserDep
) -> list[ImportProfilePublic]:
    account_id = resolve_account_id(db, current_user)
    profiles = db.scalars(
        select(ImportProfile)
        .where(ImportProfile.account_id == account_id)
        .order_by(ImportProfile.name)
    ).all()
    return [_to_public(profile) for profile in profiles]


@router.post("", response_model=ImportProfilePublic, status_code=201)
def create_import_profile(
    payload: ImportProfileCreate, db: SessionDep, current_user: CurrentUserDep
) -> ImportProfilePublic:
    account_id = resolve_account_id(db, current_user)
    profile = ImportProfile(
        account_id=account_id,
        name=payload.name,
        supplier_match=payload.supplier_match.strip().lower(),
        config_json=payload.config.model_dump(mode="json"),
    )
    db.add(profile)
    db.commit()
    db.refresh(profile)
    return _to_public(profile)


# Declared BEFORE /{profile_id}: "bulk" must not parse as a profile id.
@router.patch("/bulk", response_model=list[ImportProfilePublic])
def bulk_update_import_profiles(
    payload: ImportProfilesBulkUpdate,
    db: SessionDep,
    current_user: CurrentUserDep,
) -> list[ImportProfilePublic]:
    """Harmonize shared conventions (season, title template, color split)
    across several profiles at once — catalogue-wide settings in practice.

    Every id must belong to the caller's account (404 otherwise, nothing
    written); fields left to None are untouched on every profile.
    """
    account_id = resolve_account_id(db, current_user)
    profiles = [
        _get_profile(db, account_id=account_id, profile_id=profile_id)
        for profile_id in payload.profile_ids
    ]
    updates: dict[str, object] = {}
    if payload.season_label is not None:
        updates["season_label"] = payload.season_label.strip()
    if payload.apply_title_template is not None:
        updates["apply_title_template"] = payload.apply_title_template
    if payload.split_by_color is not None:
        updates["split_by_color"] = payload.split_by_color
    for profile in profiles:
        config = ImportProfileConfig.model_validate(
            {**(profile.config_json or {}), **updates}
        )
        profile.config_json = config.model_dump(mode="json")
    db.commit()
    for profile in profiles:
        db.refresh(profile)
    return [_to_public(profile) for profile in profiles]


@router.patch("/{profile_id}", response_model=ImportProfilePublic)
def update_import_profile(
    profile_id: int,
    payload: ImportProfileUpdate,
    db: SessionDep,
    current_user: CurrentUserDep,
) -> ImportProfilePublic:
    account_id = resolve_account_id(db, current_user)
    profile = _get_profile(db, account_id=account_id, profile_id=profile_id)
    if payload.name is not None:
        profile.name = payload.name
    if payload.supplier_match is not None:
        profile.supplier_match = payload.supplier_match.strip().lower()
    if payload.config is not None:
        profile.config_json = payload.config.model_dump(mode="json")
    db.commit()
    db.refresh(profile)
    return _to_public(profile)


@router.delete("/{profile_id}", status_code=204)
def delete_import_profile(
    profile_id: int, db: SessionDep, current_user: CurrentUserDep
) -> None:
    account_id = resolve_account_id(db, current_user)
    profile = _get_profile(db, account_id=account_id, profile_id=profile_id)
    db.delete(profile)
    db.commit()
