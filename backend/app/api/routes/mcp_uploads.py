"""Réception des images envoyées via une URL émise par le MCP.

Authentifiée par le seul jeton signé de l'URL (voir `app.mcp.uploads`) : le
client MCP envoie les octets bruts, sans cookie ni bearer. Mêmes règles que
l'upload de l'app (`POST /products/{id}/images`) : 15 Mo max, format réel
détecté (HEIC converti), nom selon le modèle du compte, ajout en fin de
galerie par l'endpoint Tillin d'ajout en masse — avec le token Tillin de
l'utilisateur, jamais l'identité de service.
"""

import logging
from typing import Any

from fastapi import APIRouter, Request
from sqlalchemy.orm import Session
from starlette.concurrency import run_in_threadpool

from app.api.deps import SessionDep, xano_client_for_user
from app.api.exceptions import AppException
from app.api.routes.products import MAX_UPLOAD_BYTES, _template_names_for_upload
from app.api.services.accounts import resolve_account_id
from app.imaging.uploads import prepare_upload
from app.mcp.uploads import UploadGrant, verify_upload
from app.models import User

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/mcp-uploads", tags=["mcp"])


def _too_large() -> AppException:
    return AppException(
        status_code=413,
        code="file_too_large",
        message=f"Image trop lourde (max {MAX_UPLOAD_BYTES // (1024 * 1024)} Mo)",
    )


@router.put("/{token}")
async def receive_upload(token: str, request: Request, db: SessionDep) -> Any:
    grant = verify_upload(token)
    if grant is None:
        raise AppException(
            status_code=401,
            code="upload_link_invalid",
            message=(
                "Lien d'envoi invalide ou expiré (30 min) : redemandez une URL "
                "avec catalogai_create_image_upload."
            ),
        )
    declared = request.headers.get("content-length")
    if declared and declared.isdigit() and int(declared) > MAX_UPLOAD_BYTES:
        raise _too_large()
    data = await request.body()
    if len(data) > MAX_UPLOAD_BYTES:
        raise _too_large()
    if not data:
        raise AppException(status_code=422, code="no_files", message="Fichier vide")
    # Base et Tillin sont synchrones : hors de la boucle d'événements.
    return await run_in_threadpool(_store, db, grant, data)


def _store(db: Session, grant: UploadGrant, data: bytes) -> dict[str, Any]:
    user = db.get(User, grant.user_id)
    if user is None or not user.is_active:
        raise AppException(
            status_code=403,
            code="user_inactive",
            message="Compte utilisateur désactivé",
        )
    # Le compte suit la dernière connexion web : si l'utilisateur a changé
    # d'entreprise depuis l'émission du lien, le token Tillin courant n'est
    # plus celui du produit visé — refus plutôt qu'écriture ailleurs.
    if resolve_account_id(db, user) != grant.account_id:
        raise AppException(
            status_code=409,
            code="account_changed",
            message=(
                "Le compte CatalogAI actif a changé depuis l'émission du lien : "
                "redemandez une URL d'envoi."
            ),
        )

    xano = xano_client_for_user(db, user)
    name = _template_names_for_upload(db, grant.account_id, xano, grant.product_id, 1)[
        0
    ]
    part = prepare_upload(name or grant.filename, data, index=0)
    created = xano.upload_product_images(grant.product_id, [part])
    if not created:
        logger.error(
            "Tillin created no image for MCP upload (product %s, %s)",
            grant.product_id,
            part[0],
        )
        raise AppException(
            status_code=502,
            code="images_rejected",
            message="Tillin n'a pas enregistré l'image : réessayez.",
        )
    image = created[0]
    logger.info(
        "mcp upload user=%s product=%s image=%s",
        grant.user_id,
        grant.product_id,
        image.id,
    )
    return {
        "product_id": grant.product_id,
        "filename": grant.filename,
        "image_id": image.id,
        "url": image.url,
    }
