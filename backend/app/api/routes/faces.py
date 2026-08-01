"""Visages mannequins du compte (face swap FASHN, « Remplacer le mannequin »).

Bibliothèque par compte : upload, liste avec prévisualisation (fichier servi
authentifié), suppression. Les fichiers vivent sous IMAGING_DIR/faces/
(exclus du sweep de rétention) et partent vers FASHN en data URI — jamais
d'URL publique.
"""

import secrets
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, Response, UploadFile
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import CurrentUserDep, SessionDep, require_feature
from app.api.exceptions import AppException
from app.api.schemas.faces import FaceReferencePublic
from app.api.services.accounts import resolve_account_id
from app.core.config import settings
from app.imaging import staging
from app.models import FaceReference

router = APIRouter(
    prefix="/faces",
    tags=["faces"],
    dependencies=[Depends(require_feature("feature_studio"))],
)

_MAX_FACE_BYTES = 8 * 1024 * 1024
_ALLOWED_TYPES = {"image/jpeg": "jpg", "image/png": "png", "image/webp": "webp"}
_CONTENT_TYPES = {"jpg": "image/jpeg", "png": "image/png", "webp": "image/webp"}


def _get_owned(db: Session, *, account_id: int, face_id: int) -> FaceReference:
    face = db.get(FaceReference, face_id)
    if face is None or face.account_id != account_id:
        raise AppException(status_code=404, code="not_found", message="Face not found")
    return face


def _to_public(face: FaceReference) -> FaceReferencePublic:
    return FaceReferencePublic(id=face.id, name=face.name, created_at=face.created_at)


@router.get("", response_model=list[FaceReferencePublic])
def list_faces(
    db: SessionDep, current_user: CurrentUserDep
) -> list[FaceReferencePublic]:
    account_id = resolve_account_id(db, current_user)
    rows = db.scalars(
        select(FaceReference)
        .where(FaceReference.account_id == account_id)
        .order_by(FaceReference.name, FaceReference.id)
    ).all()
    return [_to_public(row) for row in rows]


@router.post("", response_model=FaceReferencePublic, status_code=201)
async def upload_face(
    db: SessionDep,
    current_user: CurrentUserDep,
    file: UploadFile = File(...),
    name: str = Form(..., min_length=1, max_length=80),
) -> FaceReferencePublic:
    account_id = resolve_account_id(db, current_user)
    extension = _ALLOWED_TYPES.get(file.content_type or "")
    if extension is None:
        raise AppException(
            status_code=400,
            code="unsupported_type",
            message="Formats acceptés : JPEG, PNG, WebP",
        )
    data = await file.read()
    if len(data) > _MAX_FACE_BYTES:
        raise AppException(
            status_code=400, code="too_large", message="Image trop lourde (max 8 Mo)"
        )
    relpath = f"faces/{account_id}-{secrets.token_hex(8)}.{extension}"
    target = Path(settings.IMAGING_DIR) / relpath
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(data)
    face = FaceReference(account_id=account_id, name=name.strip(), file_path=relpath)
    db.add(face)
    db.commit()
    db.refresh(face)
    return _to_public(face)


@router.get("/{face_id}/file")
def read_face_file(
    face_id: int, db: SessionDep, current_user: CurrentUserDep
) -> Response:
    """Prévisualisation (fichier servi authentifié, jamais d'URL publique)."""
    account_id = resolve_account_id(db, current_user)
    face = _get_owned(db, account_id=account_id, face_id=face_id)
    try:
        data = staging.load(face.file_path)
    except (FileNotFoundError, ValueError) as exc:
        raise AppException(
            status_code=404, code="file_missing", message="Fichier introuvable"
        ) from exc
    extension = face.file_path.rsplit(".", 1)[-1]
    return Response(
        content=data, media_type=_CONTENT_TYPES.get(extension, "image/jpeg")
    )


@router.delete("/{face_id}", status_code=204)
def delete_face(face_id: int, db: SessionDep, current_user: CurrentUserDep) -> None:
    account_id = resolve_account_id(db, current_user)
    face = _get_owned(db, account_id=account_id, face_id=face_id)
    (Path(settings.IMAGING_DIR) / face.file_path).unlink(missing_ok=True)
    db.delete(face)
    db.commit()
