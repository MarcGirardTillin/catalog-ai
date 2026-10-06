"""Garde commune des outils MCP : mêmes droits que l'app web.

Chaque outil résout l'utilisateur du jeton, puis applique EXACTEMENT les
règles de l'API : compte actif, scoping `account_id`, module du compte
(bypass admin limité aux modules — jamais aux crédits ni au scoping), client
Xano au jeton Tillin de l'utilisateur (jamais l'identité de service). Les
erreurs de l'API deviennent des `ToolError` qui disent quoi faire.
"""

import logging
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from functools import cached_property
from typing import Literal

import anyio
from fastmcp.exceptions import ToolError
from fastmcp.server.dependencies import get_access_token
from sqlalchemy.orm import Session

from app.api.deps import xano_client_for_user
from app.api.exceptions import AppException
from app.api.services.accounts import resolve_account_id
from app.api.services.imaging import account_settings
from app.clients.base import ExternalServiceError
from app.clients.xano import XanoClient
from app.core.db import SessionLocal
from app.mcp.oauth import SCOPE_READ, SCOPE_WRITE
from app.models import User

logger = logging.getLogger("app.mcp")

Feature = Literal["feature_import", "feature_enrich", "feature_studio"]

_FEATURE_LABELS = {
    "feature_import": "import",
    "feature_enrich": "enrichissement",
    "feature_studio": "studio",
}

# Messages « quoi faire » pour les erreurs connues de l'API.
_ERROR_HINTS = {
    "xano_token_expired": (
        "Votre session Tillin a expiré (elle dure 72 h) : reconnectez-vous sur "
        "catalog.tillin.fr, puis relancez la demande."
    ),
    "insufficient_credits": (
        "Crédits insuffisants pour cette action : rechargez le compte depuis "
        "catalog.tillin.fr (page Consommation)."
    ),
}


@dataclass
class ToolContext:
    db: Session
    user: User
    account_id: int

    @cached_property
    def xano(self) -> XanoClient:
        return xano_client_for_user(self.db, self.user)


def current_user_id(*, write: bool = False) -> int:
    """Utilisateur du jeton de la requête (posé par le vérificateur), après
    contrôle du scope : `catalogai:write` pour les outils qui écrivent."""
    token = get_access_token()
    user_id = (token.claims or {}).get("user_id") if token else None
    if token is None or not isinstance(user_id, int):
        raise ToolError("Authentification requise : jeton d'API CatalogAI manquant.")
    scopes = set(token.scopes or [])
    if write and SCOPE_WRITE not in scopes:
        raise ToolError(
            "Cette connexion est en lecture seule : reconnectez CatalogAI en "
            "autorisant les actions (scope catalogai:write)."
        )
    if not scopes & {SCOPE_READ, SCOPE_WRITE}:
        raise ToolError("Cette connexion n'a accès à aucun outil CatalogAI.")
    return user_id


@contextmanager
def tool_context(user_id: int, feature: Feature | None) -> Iterator[ToolContext]:
    with SessionLocal() as db:
        user = db.get(User, user_id)
        if user is None or not user.is_active:
            raise ToolError("Ce compte utilisateur est désactivé.")
        account_id = resolve_account_id(db, user)
        if feature is not None and not user.is_admin:
            if not getattr(account_settings(db, account_id), feature):
                raise ToolError(
                    f"Le module {_FEATURE_LABELS[feature]} n'est pas activé pour "
                    "votre compte."
                )
        yield ToolContext(db=db, user=user, account_id=account_id)


def _as_tool_error(exc: Exception) -> ToolError:
    # ExternalServiceError hérite d'AppException : à tester en premier.
    if isinstance(exc, ExternalServiceError):
        service = exc.code.removesuffix("_error")
        return ToolError(
            f"Le service {service} est indisponible pour le moment : "
            "réessayez dans quelques minutes."
        )
    if isinstance(exc, AppException):
        hint = _ERROR_HINTS.get(exc.code)
        return ToolError(hint or f"{exc.message} ({exc.code})")
    return ToolError("Erreur inattendue côté CatalogAI : réessayez plus tard.")


async def run_tool[T](
    name: str,
    feature: Feature | None,
    work: Callable[[ToolContext], T],
    *,
    write: bool = False,
) -> T:
    """Exécute `work` dans un thread (routes et services synchrones) sous la
    garde commune, avec une ligne de journal par appel (sans les arguments)."""
    user_id = current_user_id(write=write)
    started = time.monotonic()
    outcome = "ok"

    def call() -> T:
        with tool_context(user_id, feature) as ctx:
            return work(ctx)

    try:
        return await anyio.to_thread.run_sync(call)
    except ToolError:
        outcome = "refused"
        raise
    except Exception as exc:
        outcome = type(exc).__name__
        if not isinstance(exc, AppException):
            logger.exception("MCP tool %s failed", name)
        raise _as_tool_error(exc) from exc
    finally:
        logger.info(
            "mcp tool=%s user=%s outcome=%s duration_ms=%d",
            name,
            user_id,
            outcome,
            (time.monotonic() - started) * 1000,
        )
