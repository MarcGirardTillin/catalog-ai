"""Photoroom client — segment (cutout RGBA) and legacy full edit.

Two endpoints, two hosts:
- `POST https://sdk.photoroom.com/v1/segment` (multipart `image_file`) —
  Remove Background plan, ~0.02 $/image. Confirmed live (2026-07-12): returns
  a PNG **RGBA** whose alpha isolates the product; sandbox keys answer 200 but
  tile a semi-transparent watermark over the whole frame.
- `GET https://image-api.photoroom.com/v2/edit` — legacy all-in-one edit
  (cutout + bg + 4:5), ~0.10 $/image. Confirmed live (2026-07-10): params as
  query params; JSON POST rejected 400. Kept until the Pillow pipeline fully
  replaces it.
"""

import httpx

from app.clients.base import ExternalServiceError, NotConfiguredError
from app.core.config import settings

BASE_URL = "https://image-api.photoroom.com"
# The segment endpoint lives on a DIFFERENT host than /v2/edit (absolute URL
# per request; the client's base_url stays on image-api).
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
