"""Authentication routes: login, logout, and current-user."""

from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Response
from pydantic import BaseModel, Field

from app.api.deps import CurrentUserDep, SessionDep
from app.api.exceptions import AppException
from app.api.schemas import LoginRequest, UserPublic
from app.api.services.accounts import get_or_create_company_account
from app.api.services.users import (
    authenticate_user,
    change_password,
    get_or_create_federated_user,
)
from app.clients.xano import verify_login
from app.core.config import settings
from app.core.security import create_access_token
from app.models import User

router = APIRouter(prefix="/auth", tags=["auth"])


def _user_public(db: SessionDep, user: User) -> UserPublic:
    """UserPublic enrichi du nom de son compte (= son entreprise Tillin)."""
    public = UserPublic.model_validate(user, from_attributes=True)
    if user.account_id is not None:
        from app.models import Account

        account = db.get(Account, user.account_id)
        public.account_name = account.name if account else None
    return public


def _set_session_cookie(response: Response, token: str) -> None:
    response.set_cookie(
        key=settings.AUTH_COOKIE_NAME,
        value=token,
        max_age=settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60,
        httponly=True,
        secure=settings.AUTH_COOKIE_SECURE,
        samesite="lax",
        path="/",
    )


def _attach_xano_identity(db: SessionDep, user: User, profile: dict[str, Any]) -> None:
    """Bind a Xano-verified login to its company account and capture the token.

    The company from `/auth/me` is authoritative: the user is (re)attached to
    that company's account — catalog calls then carry THEIR token, and every
    business row they create lands under their company. Committed with the
    token in one go.
    """
    company_id = profile.get("company_id")
    if company_id is not None:
        account = get_or_create_company_account(
            db, int(company_id), company_name=profile.get("company_name")
        )
        user.account_id = account.id
    user.xano_token = profile.get("token")
    user.xano_token_at = datetime.now(UTC)
    db.commit()


def _login_via_xano(db: SessionDep, email: str, password: str) -> User | None:
    """Fallback auth: accept valid Xano credentials, upserting a local user."""
    if not settings.xano_configured:
        return None
    profile = verify_login(
        settings.XANO_BASE_URL,
        email,
        password,
        data_source=settings.XANO_DATA_SOURCE,
    )
    if profile is None:
        return None
    user = get_or_create_federated_user(
        db, email=profile["email"], full_name=profile.get("full_name")
    )
    _attach_xano_identity(db, user, profile)
    return user


@router.post("/login", response_model=UserPublic)
def login(credentials: LoginRequest, response: Response, db: SessionDep) -> UserPublic:
    """Verify credentials and set the session cookie.

    Tries app-local users first, then falls back to Xano credentials so Tillin
    users can sign in with their Xano identifiers.

    A LOCAL success still tries the same credentials against Xano (best
    effort): when they match — the normal case for a Tillin user who also has
    a local password — we capture a fresh user token and company binding, so
    their catalog calls are company-scoped instead of falling back to the
    service identity. A mismatch changes nothing.
    """
    user = authenticate_user(db, email=credentials.email, password=credentials.password)
    if user is not None and settings.xano_configured:
        profile = verify_login(
            settings.XANO_BASE_URL,
            credentials.email,
            credentials.password,
            data_source=settings.XANO_DATA_SOURCE,
        )
        if profile is not None:
            _attach_xano_identity(db, user, profile)
    if user is None:
        user = _login_via_xano(db, credentials.email, credentials.password)
    if user is None:
        raise AppException(
            status_code=401,
            code="invalid_credentials",
            message="Incorrect email or password",
        )
    _set_session_cookie(response, create_access_token(user.id))
    return _user_public(db, user)


@router.post("/logout", status_code=204)
def logout(response: Response) -> None:
    """Clear the session cookie."""
    response.delete_cookie(key=settings.AUTH_COOKIE_NAME, path="/")


@router.get("/me", response_model=UserPublic)
def read_current_user(db: SessionDep, current_user: CurrentUserDep) -> UserPublic:
    """Return the currently authenticated user."""
    return _user_public(db, current_user)


class PasswordChangeRequest(BaseModel):
    current_password: str = Field(min_length=1)
    new_password: str = Field(min_length=8, max_length=128)


@router.post("/password", status_code=204)
def update_password(
    payload: PasswordChangeRequest, db: SessionDep, current_user: CurrentUserDep
) -> None:
    """Change the signed-in user's local password (current one required)."""
    change_password(
        db,
        current_user,
        current_password=payload.current_password,
        new_password=payload.new_password,
    )
