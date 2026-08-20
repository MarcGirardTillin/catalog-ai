"""OpenAI Images client — édition d'image `gpt-image` (mise à plat GPT).

Un seul appel : POST /v1/images/edits (multipart) avec une ou plusieurs
images sources + un prompt ; la réponse porte l'image en base64 et l'usage
en tokens (facturation OpenAI au token, séparée de tout abonnement ChatGPT).
`input_fidelity=high` préserve les détails du produit (textures, motifs) —
c'est le réglage pertinent pour du vêtement.
"""

import base64
from dataclasses import dataclass, field
from typing import Any

import httpx

from app.clients.base import ExternalServiceError, NotConfiguredError
from app.core.config import settings

BASE_URL = "https://api.openai.com/v1"

# Tailles acceptées par gpt-image (pas de WxH libre) : ratio app -> size.
GPT_IMAGE_SIZES = {
    "4:5": "1024x1536",
    "3:4": "1024x1536",
    "1:1": "1024x1024",
    "16:9": "1536x1024",
}
# Notre qualité 1k/2k/4k -> paramètre `quality` gpt-image (pas de 4k natif :
# high est le maximum).
GPT_IMAGE_QUALITY = {"1k": "medium", "2k": "high", "4k": "high"}


@dataclass
class GptImageResult:
    data: bytes
    # Usage tokens (facturation OpenAI) — {} si absent de la réponse.
    usage: dict[str, Any] = field(default_factory=dict)


class OpenAiImagesClient:
    def __init__(
        self,
        api_key: str,
        *,
        timeout: float = 180.0,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        if not api_key:
            raise NotConfiguredError("openai")
        self._client = httpx.Client(
            base_url=BASE_URL,
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=timeout,
            transport=transport,
        )

    @classmethod
    def from_settings(
        cls, *, transport: httpx.BaseTransport | None = None
    ) -> "OpenAiImagesClient":
        return cls(settings.OPENAI_API_KEY, transport=transport)

    def close(self) -> None:
        self._client.close()

    def edit_image(
        self,
        images: list[bytes],
        prompt: str,
        *,
        size: str = "1024x1536",
        quality: str = "high",
        model: str | None = None,
    ) -> GptImageResult:
        """Édite/compose une image à partir de 1..16 images sources + prompt."""
        files = [
            ("image[]", (f"source-{index}.png", data, "image/png"))
            for index, data in enumerate(images, start=1)
        ]
        payload = {
            "model": model or settings.OPENAI_IMAGE_MODEL,
            "prompt": prompt,
            "size": size,
            "quality": quality,
            "input_fidelity": "high",
            "n": "1",
        }
        try:
            response = self._client.post("/images/edits", data=payload, files=files)
        except httpx.HTTPError as exc:
            raise ExternalServiceError("openai", "OpenAI is unreachable") from exc
        if response.status_code >= 400:
            detail: dict[str, Any] = {"upstream_status": response.status_code}
            try:
                message = response.json().get("error", {}).get("message")
                if message:
                    detail["upstream_message"] = str(message)[:300]
            except ValueError:
                pass
            raise ExternalServiceError(
                "openai", "OpenAI returned an error response", detail=detail
            )
        body = response.json()
        entries = body.get("data") or []
        b64 = entries[0].get("b64_json") if entries else None
        if not b64:
            raise ExternalServiceError("openai", "OpenAI returned no image")
        return GptImageResult(
            data=base64.b64decode(b64),
            usage=body.get("usage") or {},
        )
