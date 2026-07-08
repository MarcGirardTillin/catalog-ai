"""Authentication routes: login, logout, and current-user."""

from fastapi import APIRouter, Response
from pydantic import BaseModel, Field

from app.api.deps import CurrentUserDep, SessionDep
from app.api.exceptions import AppException
from app.api.schemas import LoginRequest, UserPublic
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
    return get_or_create_federated_user(
        db, email=profile["email"], full_name=profile.get("full_name")
    )


@router.post("/login", response_model=UserPublic)
def login(credentials: LoginRequest, response: Response, db: SessionDep) -> UserPublic:
    """Verify credentials and set the session cookie.

    Tries app-local users first, then falls back to Xano credentials so Tillin
    users can sign in with their Xano identifiers.
    """
    user = authenticate_user(db, email=credentials.email, password=credentials.password)
    if user is None:
        user = _login_via_xano(db, credentials.email, credentials.password)
    if user is None:
        raise AppException(
            status_code=401,
            code="invalid_credentials",
            message="Incorrect email or password",
        )
    _set_session_cookie(response, create_access_token(user.id))
    return UserPublic.model_validate(user, from_attributes=True)


@router.post("/logout", status_code=204)
def logout(response: Response) -> None:
    """Clear the session cookie."""
    response.delete_cookie(key=settings.AUTH_COOKIE_NAME, path="/")


@router.get("/me", response_model=UserPublic)
def read_current_user(current_user: CurrentUserDep) -> UserPublic:
    """Return the currently authenticated user."""
    return UserPublic.model_validate(current_user, from_attributes=True)


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
