"""Consentement OAuth du serveur MCP (page /oauth/consent de l'app).

La demande est créée par `/authorize` (fournisseur OAuth) ; l'utilisateur
connecté (cookie de session) l'autorise ou la refuse ici. La réponse donne
l'URL de retour du client (code ou erreur), que la page ouvre.
"""

from datetime import datetime
from urllib.parse import urlparse

from fastapi import APIRouter
from pydantic import BaseModel

from app.api.deps import CurrentUserDep, SessionDep
from app.api.exceptions import AppException
from app.mcp.oauth import (
    SCOPE_READ,
    SCOPE_WRITE,
    approve_authorization,
    client_name,
    deny_authorization,
    pending_authorization,
)
from app.models import OAuthAuthorization

router = APIRouter(prefix="/oauth", tags=["oauth"])

_SCOPE_LABELS = {
    SCOPE_READ: "Lire votre catalogue, vos enrichissements et vos imports",
    SCOPE_WRITE: (
        "Lancer des enrichissements (débite des crédits), valider des fiches, "
        "appliquer dans Tillin et transférer des imports — toujours après un "
        "aperçu et votre confirmation dans la conversation"
    ),
}


class OAuthScopePublic(BaseModel):
    scope: str
    label: str


class OAuthRequestPublic(BaseModel):
    client_name: str
    redirect_host: str
    scopes: list[OAuthScopePublic]
    expires_at: datetime


class OAuthDecision(BaseModel):
    redirect_url: str


def _pending(db: SessionDep, request_key: str) -> OAuthAuthorization:
    row = pending_authorization(db, request_key)
    if row is None:
        raise AppException(
            status_code=404,
            code="oauth_request_expired",
            message="Cette demande d'autorisation a expiré : relancez la connexion.",
        )
    return row


@router.get("/requests/{request_key}", response_model=OAuthRequestPublic)
def read_request(
    request_key: str, db: SessionDep, _current_user: CurrentUserDep
) -> OAuthRequestPublic:
    row = _pending(db, request_key)
    return OAuthRequestPublic(
        client_name=client_name(db, row.client_id),
        redirect_host=urlparse(row.redirect_uri).hostname or row.redirect_uri,
        scopes=[
            OAuthScopePublic(scope=scope, label=_SCOPE_LABELS.get(scope, scope))
            for scope in row.scopes_json or []
        ],
        expires_at=row.expires_at,
    )


@router.post("/requests/{request_key}/approve", response_model=OAuthDecision)
def approve_request(
    request_key: str, db: SessionDep, current_user: CurrentUserDep
) -> OAuthDecision:
    row = _pending(db, request_key)
    return OAuthDecision(redirect_url=approve_authorization(db, row, current_user))


@router.post("/requests/{request_key}/deny", response_model=OAuthDecision)
def deny_request(
    request_key: str, db: SessionDep, _current_user: CurrentUserDep
) -> OAuthDecision:
    row = _pending(db, request_key)
    return OAuthDecision(redirect_url=deny_authorization(db, row))
