"""URLs d'envoi d'images locales pour le MCP (modèle « URL signée »).

Un client MCP ne peut pas pousser un fichier dans un appel d'outil (il
faudrait recopier les octets en base64 dans les arguments). L'outil
`catalogai_create_image_upload` émet donc, par fichier, une URL à usage court
portant un jeton signé (utilisateur, compte, produit, nom de fichier) ; le
client y envoie les octets (`curl -X PUT --data-binary @photo.jpg <url>`) et
la route `PUT /mcp-uploads/{jeton}` les transmet aussitôt à Tillin par
l'endpoint d'ajout d'images de l'app. Sans état : pas de stockage
intermédiaire, rien à purger, valable sur plusieurs workers.
"""

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import jwt

from app.core.config import settings

UPLOAD_AUDIENCE = "catalogai-image-upload"
UPLOAD_TTL = timedelta(minutes=30)


@dataclass(frozen=True)
class UploadGrant:
    user_id: int
    account_id: int
    product_id: int
    filename: str


def sign_upload(grant: UploadGrant, *, now: datetime | None = None) -> str:
    issued = now or datetime.now(UTC)
    payload = {
        "aud": UPLOAD_AUDIENCE,
        "sub": str(grant.user_id),
        "acc": grant.account_id,
        "pid": grant.product_id,
        "fn": grant.filename,
        "iat": issued,
        "exp": issued + UPLOAD_TTL,
    }
    return jwt.encode(payload, settings.APP_SECRET, algorithm=settings.JWT_ALGORITHM)


def verify_upload(token: str) -> UploadGrant | None:
    """Le grant d'un jeton valide (signature, audience, expiration), sinon None.

    L'audience dédiée empêche qu'un cookie de session (même secret) serve
    d'URL d'envoi, et inversement.
    """
    try:
        payload = jwt.decode(
            token,
            settings.APP_SECRET,
            algorithms=[settings.JWT_ALGORITHM],
            audience=UPLOAD_AUDIENCE,
        )
        return UploadGrant(
            user_id=int(payload["sub"]),
            account_id=int(payload["acc"]),
            product_id=int(payload["pid"]),
            filename=str(payload["fn"]),
        )
    except (jwt.InvalidTokenError, KeyError, TypeError, ValueError):
        return None


def upload_url(token: str) -> str:
    return f"{settings.PUBLIC_API_URL}/mcp-uploads/{token}"


# --- Liens de lecture des images Studio ---------------------------------------
# Image traitée lisible SANS connexion (mesure du fond avant validation) :
# lien signé, audience dédiée, 24 h, limité à un actif du compte.

STUDIO_FILE_AUDIENCE = "catalogai-studio-file"
STUDIO_FILE_TTL = timedelta(hours=24)


def sign_studio_file(
    asset_id: int, account_id: int, *, now: datetime | None = None
) -> str:
    issued = now or datetime.now(UTC)
    payload = {
        "aud": STUDIO_FILE_AUDIENCE,
        "ast": asset_id,
        "acc": account_id,
        "iat": issued,
        "exp": issued + STUDIO_FILE_TTL,
    }
    return jwt.encode(payload, settings.APP_SECRET, algorithm=settings.JWT_ALGORITHM)


def verify_studio_file(token: str) -> tuple[int, int] | None:
    """(asset_id, account_id) d'un lien valide, sinon None."""
    try:
        payload = jwt.decode(
            token,
            settings.APP_SECRET,
            algorithms=[settings.JWT_ALGORITHM],
            audience=STUDIO_FILE_AUDIENCE,
        )
        return int(payload["ast"]), int(payload["acc"])
    except (jwt.InvalidTokenError, KeyError, TypeError, ValueError):
        return None


def studio_file_url(token: str) -> str:
    return f"{settings.PUBLIC_API_URL}/mcp-files/{token}"
