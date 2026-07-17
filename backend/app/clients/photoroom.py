"""Photoroom client — segment (cutout RGBA) + /v2/edit (features IA, plan Plus).

`POST https://sdk.photoroom.com/v1/segment` (multipart `image_file`),
~0.02 $/image. Confirmed live (2026-07-12): returns a PNG **RGBA** whose alpha
isolates the product; sandbox keys answer 200 but tile a semi-transparent
watermark over the whole frame. Everything downstream (background, ratio,
centering, compression) is local Pillow (`app.imaging.compose`).

`/v2/edit` (host `image-api.photoroom.com`) porte les features IA facturées
0,10 $/image quel que soit le nombre d'options combinées dans l'appel (flat
lay, ghost mannequin, virtual model, ombres, décors IA, défroissage, upscale,
beautifier, editWithAI…). GET + query params quand l'entrée est une URL
publique, POST multipart `imageFile` pour des bytes. Confirmé live 2026-07-10
(le POST JSON est rejeté). La clé edit peut différer de la clé segment pendant
la phase de test sandbox (`PHOTOROOM_EDIT_API_KEY`, repli sur la clé
principale).
"""

from typing import Any

import httpx

from app.clients.base import ExternalServiceError, NotConfiguredError
from app.core.config import settings

BASE_URL = "https://image-api.photoroom.com"
# The segment endpoint lives on its own host (absolute URL per request).
SEGMENT_URL = "https://sdk.photoroom.com/v1/segment"
EDIT_PATH = "/v2/edit"
# virtualModel/flatLay peuvent être lents — timeout dédié aux appels edit.
EDIT_TIMEOUT = 120.0


def _flatten_params(params: dict[str, Any], prefix: str = "") -> dict[str, str]:
    """Aplati un dict imbriqué en notation pointée pour les query params.

    `{"flatLay": {"mode": "ai.auto"}}` → `{"flatLay.mode": "ai.auto"}` ;
    les listes deviennent `a[0].b`, les booléens `"true"/"false"` ; les
    valeurs None sont omises.
    """
    flat: dict[str, str] = {}
    for key, value in params.items():
        full_key = f"{prefix}.{key}" if prefix else key
        if value is None:
            continue
        if isinstance(value, dict):
            flat.update(_flatten_params(value, full_key))
        elif isinstance(value, list):
            for index, item in enumerate(value):
                indexed = f"{full_key}[{index}]"
                if isinstance(item, dict):
                    flat.update(_flatten_params(item, indexed))
                elif item is not None:
                    flat[indexed] = str(item)
        elif isinstance(value, bool):
            flat[full_key] = "true" if value else "false"
        else:
            flat[full_key] = str(value)
    return flat


class PhotoroomClient:
    def __init__(
        self,
        api_key: str,
        *,
        edit_api_key: str = "",
        timeout: float = 60.0,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        if not api_key and not edit_api_key:
            raise NotConfiguredError("photoroom")
        self._client = httpx.Client(
            base_url=BASE_URL,
            headers={"x-api-key": api_key or edit_api_key},
            timeout=timeout,
            transport=transport,
        )
        # La clé edit (sandbox pendant la phase de test) prime pour /v2/edit ;
        # vide = la clé principale sert pour tout.
        self._edit_api_key = edit_api_key or api_key

    @classmethod
    def from_settings(
        cls, *, transport: httpx.BaseTransport | None = None
    ) -> "PhotoroomClient":
        return cls(
            settings.PHOTOROOM_API_KEY,
            edit_api_key=settings.PHOTOROOM_EDIT_API_KEY,
            transport=transport,
        )

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> "PhotoroomClient":
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def remove_background(
        self, image_bytes: bytes, *, filename: str = "image.png"
    ) -> bytes:
        """Cut out the subject: returns a PNG with an alpha channel (RGBA)."""
        try:
            response = self._client.post(
                SEGMENT_URL,
                files={
                    "image_file": (filename, image_bytes, "application/octet-stream")
                },
            )
        except httpx.HTTPError as exc:
            raise ExternalServiceError("photoroom", "Photoroom is unreachable") from exc
        if response.status_code >= 400:
            raise ExternalServiceError(
                "photoroom",
                "Photoroom returned an error response",
                detail={"upstream_status": response.status_code},
            )
        return response.content

    def edit(
        self,
        params: dict[str, Any],
        *,
        image_url: str | None = None,
        image_bytes: bytes | None = None,
        filename: str = "image.png",
    ) -> bytes:
        """Appel /v2/edit : GET si l'entrée est une URL publique, POST
        multipart `imageFile` pour des bytes (le staging local n'est pas
        public). Retourne les bytes de l'image résultat."""
        if (image_url is None) == (image_bytes is None):
            raise ValueError("edit() takes exactly one of image_url or image_bytes")
        flat = _flatten_params(params)
        headers = {"x-api-key": self._edit_api_key}
        try:
            if image_url is not None:
                response = self._client.get(
                    EDIT_PATH,
                    params={**flat, "imageUrl": image_url},
                    headers=headers,
                    timeout=EDIT_TIMEOUT,
                )
            elif image_bytes is not None:
                response = self._client.post(
                    EDIT_PATH,
                    data=flat,
                    files={
                        "imageFile": (filename, image_bytes, "application/octet-stream")
                    },
                    headers=headers,
                    timeout=EDIT_TIMEOUT,
                )
            else:  # pragma: no cover — exclu par la garde d'entrée
                raise AssertionError("unreachable")
        except httpx.HTTPError as exc:
            raise ExternalServiceError("photoroom", "Photoroom is unreachable") from exc
        if response.status_code >= 400:
            # Les erreurs /v2/edit sont des JSON explicites — précieux en debug.
            raise ExternalServiceError(
                "photoroom",
                "Photoroom returned an error response",
                detail={
                    "upstream_status": response.status_code,
                    "upstream_body": response.text[:500],
                },
            )
        return response.content
