"""Authentication routes: login, logout, and current-user."""

from fastapi import APIRouter, Response

from app.api.deps import CurrentUserDep, SessionDep
from app.api.exceptions import AppException
from app.api.schemas import LoginRequest, UserPublic
from app.api.services.users import authenticate_user
from app.core.config import settings
from app.core.security import create_access_token

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


@router.post("/login", response_model=UserPublic)
def login(credentials: LoginRequest, response: Response, db: SessionDep) -> UserPublic:
    """Verify credentials and set the session cookie."""
    user = authenticate_user(db, email=credentials.email, password=credentials.password)
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
