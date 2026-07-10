"""Photoroom client — background removal/recolor + 4:5 framing in one call.

Confirmed live (2026-07-10): `/v2/edit` takes the parameters as **query params
on a GET** (`imageUrl`, `background.color`, `outputSize`, `padding`,
`export.format`, `export.quality`); a JSON POST is rejected with 400 ("Only
multipart form data is supported") — multipart POST is the documented path for
raw file input (`imageFile`), kept for a later bytes-input need.

TODO(plan open item): confirm the transparent cutout can be returned for the
Pillow manual-recenter path.
"""

import httpx

from app.clients.base import ExternalServiceError, NotConfiguredError
from app.core.config import settings

BASE_URL = "https://image-api.photoroom.com"


class PhotoroomClient:
    def __init__(
        self,
        api_key: str,
        *,
        timeout: float = 60.0,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        if not api_key:
            raise NotConfiguredError("photoroom")
        self._client = httpx.Client(
            base_url=BASE_URL,
            headers={"x-api-key": api_key},
            timeout=timeout,
            transport=transport,
        )

    @classmethod
    def from_settings(
        cls, *, transport: httpx.BaseTransport | None = None
    ) -> "PhotoroomClient":
        return cls(settings.PHOTOROOM_API_KEY, transport=transport)

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> "PhotoroomClient":
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def edit_image(
        self,
        image_url: str,
        *,
        background_color: str = "FFFFFF",
        output_size: str = "1600x2000",
        padding: str = "10%",
        export_format: str = "webp",
        quality: int | None = None,
    ) -> bytes:
        """Cut out the product, recolor the background, pad to 4:5.

        Returns the processed image bytes; storage is the caller's concern.
        """
        params: dict[str, str | int] = {
            "imageUrl": image_url,
            "background.color": background_color,
            "outputSize": output_size,
            "padding": padding,
            "export.format": export_format,
        }
        if quality is not None:
            params["export.quality"] = quality
        try:
            response = self._client.get("/v2/edit", params=params)
        except httpx.HTTPError as exc:
            raise ExternalServiceError("photoroom", "Photoroom is unreachable") from exc
        if response.status_code >= 400:
            raise ExternalServiceError(
                "photoroom",
                "Photoroom returned an error response",
                detail={"upstream_status": response.status_code},
            )
        return response.content
