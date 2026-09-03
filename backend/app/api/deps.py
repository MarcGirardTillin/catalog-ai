"""Shared FastAPI dependencies for DB access and external clients."""

import threading
from collections.abc import Callable, Generator
from typing import TYPE_CHECKING, Annotated, cast

from fastapi import Cookie, Depends, Request
from sqlalchemy.orm import Session

from app.api.exceptions import AppException
from app.api.services.accounts import (
    freshest_company_token,
    launcher_token,
    resolve_account_id,
)
from app.api.services.users import get_user_by_id
from app.clients.base import NotConfiguredError
from app.clients.fashn import FashnClient
from app.clients.openai_images import OpenAiImagesClient
from app.clients.photoroom import PhotoroomClient
from app.clients.xano import XanoClient
from app.core.config import settings
from app.core.db import SessionLocal
from app.core.security import decode_access_token
from app.models import Account, User


def get_db() -> Generator[Session]:
    """Yield a SQLAlchemy session scoped to the current request."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


SessionDep = Annotated[Session, Depends(get_db)]


# --- Xano clients (multi-tenant) --------------------------------------------
#
# Catalog calls carry the USER'S Xano token: Xano scopes every response to the
# token's company, so tenancy is enforced upstream, not by our filters.
# Les requêtes interactives utilisent le token de l'UTILISATEUR CONNECTÉ
# (décision Marc 2026-07-30, incident Neiwa/Madel : le token « le plus
# frais du compte » pouvait être celui d'un admin ayant changé d'entreprise
# côté Tillin). Les jobs de fond, sans session, gardent la résolution par
# compte — en excluant les admins plateforme du pool de tokens.
#
# Un client long-vécu par TOKEN (pool httpx + cache marques), partagé entre
# requêtes ; les vieux clients ne sont pas fermés (un job peut encore les
# utiliser) — fuite bornée par la rotation des tokens (TTL 72 h).
#
# The service-identity client (env credentials) survives ONLY as the fallback
# for the legacy default account (app-local operator/dev users, no company).
_service_xano_client: XanoClient | None = None
_token_clients: dict[str, XanoClient] = {}
_company_clients_lock = threading.Lock()


def _require_xano_configured() -> None:
    if not settings.xano_configured:
        raise AppException(
            status_code=503,
            code="xano_not_configured",
            message="Xano integration is not configured",
        )


def get_service_xano_client() -> XanoClient:
    """The shared service-identity client (legacy default account only)."""
    global _service_xano_client
    _require_xano_configured()
    if _service_xano_client is None:
        _service_xano_client = XanoClient(
            settings.XANO_BASE_URL,
            email=settings.XANO_LOGIN_EMAIL,
            password=settings.XANO_LOGIN_PASSWORD,
            data_source=settings.XANO_DATA_SOURCE,
            timeout=settings.XANO_TIMEOUT_SECONDS,
        )
    return _service_xano_client


def _client_for_token(token: str) -> XanoClient:
    """One shared client per token (httpx pool + brand cache)."""
    cached = _token_clients.get(token)
    if cached is not None:
        return cached
    with _company_clients_lock:
        cached = _token_clients.get(token)
        if cached is not None:
            return cached
        client = XanoClient(
            settings.XANO_BASE_URL,
            token=token,
            data_source=settings.XANO_DATA_SOURCE,
            timeout=settings.XANO_TIMEOUT_SECONDS,
        )
        # Les anciens clients ne sont PAS fermés : un job de fond peut être en
        # train de les utiliser. La rotation suit les re-logins — fuite bornée.
        _token_clients[token] = client
        return client


def _legacy_fallback_or_401(db: Session, account_id: int) -> XanoClient:
    account = db.get(Account, account_id)
    if account is not None and account.xano_company_id is None:
        return get_service_xano_client()
    raise AppException(
        status_code=401,
        code="xano_token_expired",
        message="Session Tillin expirée — reconnectez-vous.",
    )


def xano_client_for_user(db: Session, user: User) -> XanoClient:
    """The Xano client acting as THE SIGNED-IN USER (his own token).

    Jamais le token d'un collègue : les réponses Xano sont scopées à
    l'entreprise portée par le token, et l'entreprise d'un AUTRE utilisateur
    peut changer côté Tillin (incident Neiwa/Madel du 2026-07-30). Sans token
    utilisable : repli service pour le compte legacy (sans entreprise), sinon
    401 xano_token_expired.
    """
    _require_xano_configured()
    if user.xano_token:
        return _client_for_token(user.xano_token)
    # resolve_account_id rattache aussi les utilisateurs legacy sans compte.
    return _legacy_fallback_or_401(db, resolve_account_id(db, user))


def xano_client_for_account(
    db: Session, account_id: int, *, launcher_user_id: int | None = None
) -> XanoClient:
    """The Xano client acting on behalf of an account (background jobs only).

    `launcher_user_id` : l'utilisateur qui a lancé le job — son token est
    préféré (admin compris : geste explicite, il voyait les produits qu'il a
    sélectionnés), repli sur le pool du compte s'il n'est plus utilisable.

    Sans session utilisateur, on prend le token le plus frais parmi les
    utilisateurs NON ADMIN du compte (un admin plateforme peut changer
    d'entreprise dans Tillin — son token ne représente pas le compte).
    No usable token:
    - legacy default account (no company) -> service-identity fallback, so the
      operator and local dev keep working;
    - company account -> 401 `xano_token_expired`: serving another company's
      data would be a cross-tenant leak, failing is the only correct answer.
    """
    _require_xano_configured()
    token = None
    if launcher_user_id is not None:
        token = launcher_token(db, account_id, launcher_user_id)
    if token is None:
        token = freshest_company_token(db, account_id)
    if token is None:
        return _legacy_fallback_or_401(db, account_id)
    return _client_for_token(token)


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


# Variantes « optionnelles » pour les routes multi-moteurs (generate-model :
# FASHN ou Photoroom au choix par appel) : un provider non configuré donne
# None au lieu d'un 503 — la route ne lève que si le moteur CHOISI manque.
# Les overrides de test posés sur get_*_client sont honorés explicitement.
def get_photoroom_client_optional(request: Request) -> PhotoroomClient | None:
    provider = request.app.dependency_overrides.get(
        get_photoroom_client, get_photoroom_client
    )
    try:
        return cast(PhotoroomClient, provider())
    except NotConfiguredError:
        return None


def get_fashn_client_optional(request: Request) -> FashnClient | None:
    provider = request.app.dependency_overrides.get(get_fashn_client, get_fashn_client)
    try:
        return cast(FashnClient, provider())
    except NotConfiguredError:
        return None


_openai_images_client: OpenAiImagesClient | None = None


def get_openai_images_client() -> OpenAiImagesClient:
    global _openai_images_client
    if _openai_images_client is None:
        _openai_images_client = OpenAiImagesClient.from_settings()
    return _openai_images_client


def get_openai_images_client_optional(request: Request) -> OpenAiImagesClient | None:
    provider = request.app.dependency_overrides.get(
        get_openai_images_client, get_openai_images_client
    )
    try:
        return cast(OpenAiImagesClient, provider())
    except NotConfiguredError:
        return None


OptionalPhotoroomDep = Annotated[
    PhotoroomClient | None, Depends(get_photoroom_client_optional)
]
OptionalFashnDep = Annotated[FashnClient | None, Depends(get_fashn_client_optional)]
OptionalOpenAiImagesDep = Annotated[
    OpenAiImagesClient | None, Depends(get_openai_images_client_optional)
]


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


def get_xano_client(db: SessionDep, current_user: CurrentUserDep) -> XanoClient:
    """Xano client for the request, acting as the signed-in user himself."""
    return xano_client_for_user(db, current_user)


XanoDep = Annotated[XanoClient, Depends(get_xano_client)]


def get_xano_client_optional(
    request: Request, db: SessionDep, current_user: CurrentUserDep
) -> XanoClient | None:
    """Xano « best-effort » : None quand le catalogue n'est pas joignable.

    Pour les routes qui n'en font qu'un ENRICHISSEMENT du rendu (ex. poids
    par défaut par catégorie sur l'aperçu CSV) — jamais un 503. Les overrides
    de test posés sur get_xano_client sont honorés.
    """
    override = request.app.dependency_overrides.get(get_xano_client)
    if override is not None:
        return cast(XanoClient, override())
    try:
        return get_xano_client(db, current_user)
    except (NotConfiguredError, AppException):
        return None


OptionalXanoDep = Annotated[XanoClient | None, Depends(get_xano_client_optional)]


def require_feature(feature: str) -> Callable[[Session, User], None]:
    """Router/route guard: 403 when the account's module is switched off.

    `feature` is the AccountSettings field name (feature_import /
    feature_enrich / feature_studio) — the operator's per-account offer,
    toggled from the admin console. The platform admin bypasses the guard
    (support/debug never depends on what a client bought).
    """

    def dependency(db: SessionDep, current_user: CurrentUserDep) -> None:
        if current_user.is_admin:
            return
        from app.api.services.imaging import account_settings

        account_id = resolve_account_id(db, current_user)
        if not getattr(account_settings(db, account_id), feature):
            raise AppException(
                status_code=403,
                code="feature_disabled",
                message="Ce module n'est pas activé pour votre compte.",
            )

    return dependency


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
