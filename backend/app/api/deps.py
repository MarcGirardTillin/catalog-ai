"""Shared FastAPI dependencies for DB access and external clients."""

from collections.abc import Callable, Generator
from typing import TYPE_CHECKING, Annotated

from fastapi import Cookie, Depends
from sqlalchemy.orm import Session

from app.api.exceptions import AppException
from app.api.services.users import get_user_by_id
from app.clients.fashn import FashnClient
from app.clients.photoroom import PhotoroomClient
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


# Imaging provider clients (same process-wide pattern as Xano: one httpx pool
# reused across requests). `from_settings` raises NotConfiguredError -> a clean
# 503 at dependency-resolution time, BEFORE any asset row is created.
_photoroom_client: PhotoroomClient | None = None


def get_photoroom_client() -> PhotoroomClient:
    global _photoroom_client
    if _photoroom_client is None:
        _photoroom_client = PhotoroomClient.from_settings()
    return _photoroom_client


_fashn_client: FashnClient | None = None


def get_fashn_client() -> FashnClient:
    global _fashn_client
    if _fashn_client is None:
        _fashn_client = FashnClient.from_settings()
    return _fashn_client


PhotoroomDep = Annotated[PhotoroomClient, Depends(get_photoroom_client)]
FashnDep = Annotated[FashnClient, Depends(get_fashn_client)]


# Background job runner. Injected so the route can schedule enrichment after a
# job is created, and so tests can override it with a no-op / spy.
JobRunner = Callable[[int], None]


def get_job_runner() -> JobRunner:
    from app.jobs.runner import process_pending

    return process_pending


JobRunnerDep = Annotated[JobRunner, Depends(get_job_runner)]


# Background import runner (same pattern: overridden with a no-op/spy in tests).
ImportRunner = Callable[[int], None]


def get_import_runner() -> ImportRunner:
    from app.jobs.import_runner import run_import_job

    return run_import_job


ImportRunnerDep = Annotated[ImportRunner, Depends(get_import_runner)]


def get_enrichment_pipeline() -> "EnrichmentPipeline":
    """Return the process-wide enrichment pipeline (manual re-resolve, etc.)."""
    from app.jobs.runner import get_pipeline

    return get_pipeline()


if TYPE_CHECKING:
    from app.enrich.pipeline import EnrichmentPipeline

PipelineDep = Annotated["EnrichmentPipeline", Depends(get_enrichment_pipeline)]


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


def get_current_admin(current_user: CurrentUserDep) -> User:
    """The signed-in user, required to be a platform admin (else 403).

    Guards everything white-label-sensitive: pricing grid, billing
    coefficient, per-model/per-provider breakdowns, cross-account monitoring.
    """
    if not current_user.is_admin:
        raise AppException(
            status_code=403, code="admin_required", message="Admin access required"
        )
    return current_user


CurrentAdminDep = Annotated[User, Depends(get_current_admin)]
