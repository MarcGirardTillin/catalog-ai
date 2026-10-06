"""Jetons d'API personnels de l'utilisateur connecté (accès MCP).

Chaque utilisateur ne voit et ne révoque que SES jetons ; un jeton agit avec
ses droits (pas de garde de module ici : la gestion des accès n'est pas un
module souscrit).
"""

from datetime import datetime

from fastapi import APIRouter
from pydantic import BaseModel, Field

from app.api.deps import CurrentUserDep, SessionDep
from app.api.services.api_tokens import (
    DEFAULT_TTL_DAYS,
    MAX_TTL_DAYS,
    create_api_token,
    is_active,
    list_api_tokens,
    revoke_api_token,
)
from app.models import ApiToken

router = APIRouter(prefix="/api-tokens", tags=["api-tokens"])


class ApiTokenPublic(BaseModel):
    id: int
    name: str
    prefix: str
    created_at: datetime
    last_used_at: datetime | None = None
    expires_at: datetime | None = None
    revoked_at: datetime | None = None
    active: bool


class ApiTokenCreate(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    ttl_days: int = Field(default=DEFAULT_TTL_DAYS, ge=1, le=MAX_TTL_DAYS)


class ApiTokenCreated(BaseModel):
    token: ApiTokenPublic
    # Jeton en clair : affiché UNE fois, jamais relisible ensuite.
    secret: str


def _to_public(token: ApiToken) -> ApiTokenPublic:
    return ApiTokenPublic(
        id=token.id,
        name=token.name,
        prefix=token.prefix,
        created_at=token.created_at,
        last_used_at=token.last_used_at,
        expires_at=token.expires_at,
        revoked_at=token.revoked_at,
        active=is_active(token),
    )


@router.get("", response_model=list[ApiTokenPublic])
def list_tokens(db: SessionDep, current_user: CurrentUserDep) -> list[ApiTokenPublic]:
    return [_to_public(token) for token in list_api_tokens(db, current_user)]


@router.post("", response_model=ApiTokenCreated, status_code=201)
def create_token(
    payload: ApiTokenCreate, db: SessionDep, current_user: CurrentUserDep
) -> ApiTokenCreated:
    token, secret = create_api_token(
        db, current_user, name=payload.name, ttl_days=payload.ttl_days
    )
    return ApiTokenCreated(token=_to_public(token), secret=secret)


@router.delete("/{token_id}", response_model=ApiTokenPublic)
def revoke_token(
    token_id: int, db: SessionDep, current_user: CurrentUserDep
) -> ApiTokenPublic:
    return _to_public(revoke_api_token(db, current_user, token_id))
