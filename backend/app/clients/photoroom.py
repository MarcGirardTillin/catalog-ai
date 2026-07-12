"""Photoroom client — segment: cutout RGBA (Remove Background plan).

`POST https://sdk.photoroom.com/v1/segment` (multipart `image_file`),
~0.02 $/image. Confirmed live (2026-07-12): returns a PNG **RGBA** whose alpha
isolates the product; sandbox keys answer 200 but tile a semi-transparent
watermark over the whole frame. Everything downstream (background, ratio,
centering, compression) is local Pillow (`app.imaging.compose`) — the legacy
all-in-one `/v2/edit` (0.10 $/image) was removed with the Pillow pipeline.
"""

import httpx

from app.clients.base import ExternalServiceError, NotConfiguredError
from app.core.config import settings

BASE_URL = "https://image-api.photoroom.com"
# The segment endpoint lives on its own host (absolute URL per request).
SEGMENT_URL = "https://sdk.photoroom.com/v1/segment"


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
