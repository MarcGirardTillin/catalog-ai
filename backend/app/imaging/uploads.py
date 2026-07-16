"""Normalisation des images déposées par le navigateur (upload / photo).

Tillin (Xano) refuse SILENCIEUSEMENT certains fichiers sur
``/product_image/{id}/bulk`` : il répond 200 avec ``images: []`` au lieu d'une
erreur. Deux cas confirmés live (2026-07-16) : un nom de fichier SANS
extension, et un format qu'il ne sait pas décoder (HEIC — le défaut des photos
iPhone). Le fichier était donc perdu sans explication.

On ne fait plus confiance à ce que déclare le navigateur : chaque image est
décodée ici (Pillow, + pillow-heif pour HEIC/HEIF), convertie en JPEG quand
son format n'est pas transférable tel quel, et renommée avec l'extension du
format RÉEL. Ce qui sort de ce module est toujours accepté par Xano.
"""

import io
import re
from pathlib import PurePosixPath

from PIL import Image, UnidentifiedImageError
from pillow_heif import register_heif_opener

from app.api.exceptions import AppException

# Enregistre le décodeur HEIC/HEIF auprès de Pillow (photos iPhone).
register_heif_opener()

# Formats que Tillin accepte tels quels (validés live) : on garde les octets
# d'origine, sans réencodage. Tout le reste est converti en JPEG.
PASSTHROUGH_FORMATS = {
    "JPEG": ("jpg", "image/jpeg"),
    "PNG": ("png", "image/png"),
    "WEBP": ("webp", "image/webp"),
}

JPEG_QUALITY = 90

_SAFE_STEM = re.compile(r"[^A-Za-z0-9._-]+")


def _safe_stem(filename: str) -> str:
    """Nom de base sans chemin ni caractère exotique ('' si rien d'exploitable)."""
    stem = PurePosixPath(filename.replace("\\", "/")).stem
    cleaned = _SAFE_STEM.sub("-", stem).strip("-._")
    return cleaned[:80]


def prepare_upload(
    filename: str | None, data: bytes, *, index: int = 0
) -> tuple[str, bytes, str]:
    """Valide et normalise une image déposée -> (nom, octets, content-type).

    Le content-type annoncé par le navigateur est ignoré : seul le contenu
    réel fait foi. Lève un 422 `not_an_image` si les octets ne sont pas une
    image décodable.
    """
    try:
        with Image.open(io.BytesIO(data)) as image:
            image_format = (image.format or "").upper()
            if image_format in PASSTHROUGH_FORMATS:
                extension, media_type = PASSTHROUGH_FORMATS[image_format]
                payload = data
            else:
                # HEIC, TIFF, BMP, GIF… : Tillin ne les reprend pas — on
                # convertit (RGB : JPEG n'a ni alpha ni palette).
                payload_buffer = io.BytesIO()
                image.convert("RGB").save(
                    payload_buffer, format="JPEG", quality=JPEG_QUALITY
                )
                payload = payload_buffer.getvalue()
                extension, media_type = "jpg", "image/jpeg"
    except (UnidentifiedImageError, OSError, ValueError) as exc:
        raise AppException(
            status_code=422,
            code="not_an_image",
            message=(
                f"{filename or 'Le fichier'} n'est pas une image lisible "
                "(formats acceptés : JPEG, PNG, WEBP, HEIC)."
            ),
        ) from exc

    # Nom TOUJOURS suffixé par l'extension du format réel : sans extension,
    # Xano jette le fichier sans le dire.
    stem = _safe_stem(filename or "") or f"image-{index + 1}"
    return f"{stem}.{extension}", payload, media_type
