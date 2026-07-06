"""Shared FastAPI dependencies for DB access and external clients."""

from collections.abc import Generator
from typing import Annotated

from fastapi import Cookie, Depends
from sqlalchemy.orm import Session

from app.api.exceptions import AppException
from app.api.services.users import get_user_by_id
from app.clients.xano import XanoClient
from app.core.config import settings
from app.core.db import SessionLocal
from app.core.security import decode_access_token
from app.models import User


def get_db() -> Generator[Session]:
    """Yield a SQLAlchemy session scoped to the current request."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


SessionDep = Annotated[Session, Depends(get_db)]


# Process-wide client: one httpx pool and one cached login token reused across
# requests (re-login happens lazily on a 401). Not per-request — that would log
# in on every call.
_xano_client: XanoClient | None = None


def get_xano_client() -> XanoClient:
    """Return the shared Xano client, or fail clearly when unconfigured."""
    global _xano_client
    if not settings.xano_configured:
        raise AppException(
            status_code=503,
            code="xano_not_configured",
            message="Xano integration is not configured",
        )
    if _xano_client is None:
        _xano_client = XanoClient(
            settings.XANO_BASE_URL,
            email=settings.XANO_LOGIN_EMAIL,
            password=settings.XANO_LOGIN_PASSWORD,
            data_source=settings.XANO_DATA_SOURCE,
            timeout=settings.XANO_TIMEOUT_SECONDS,
        )
    return _xano_client


XanoDep = Annotated[XanoClient, Depends(get_xano_client)]


def _unauthenticated() -> AppException:
    return AppException(
        status_code=401, code="not_authenticated", message="Not authenticated"
    )


def get_current_user(
    db: SessionDep,
    session_token: Annotated[
        str | None, Cookie(alias=settings.AUTH_COOKIE_NAME)
    ] = None,
) -> User:
    """Resolve the signed-in user from the session cookie, or raise 401."""
    if not session_token:
        raise _unauthenticated()
    subject = decode_access_token(session_token)
    if subject is None:
        raise _unauthenticated()
    try:
        user_id = int(subject)
    except ValueError:
        raise _unauthenticated() from None
    user = get_user_by_id(db, user_id)
    if user is None or not user.is_active:
        raise _unauthenticated()
    return user


CurrentUserDep = Annotated[User, Depends(get_current_user)]
