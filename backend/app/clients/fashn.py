"""FASHN client — generative fashion imagery (`product-to-model`).

Prediction lifecycle: `run` submits (POST /run) and returns a prediction id,
`wait` polls GET /status/{id} until `completed`/`failed`, and `download`
fetches each output URL immediately — the CDN URLs expire, so callers must
never store the bare URL (staging owns the bytes).
"""

import time
from typing import Any

import httpx

from app.clients.base import ExternalServiceError, NotConfiguredError
from app.core.config import settings

BASE_URL = "https://api.fashn.ai/v1"

# Statuses meaning "still working" — keep polling.
_PENDING_STATUSES = frozenset({"starting", "in_queue", "processing"})


class FashnClient:
    def __init__(
        self,
        api_key: str,
        *,
        timeout: float = 60.0,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        if not api_key:
            raise NotConfiguredError("fashn")
        self._client = httpx.Client(
            base_url=BASE_URL,
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=timeout,
            transport=transport,
        )

    @classmethod
    def from_settings(
        cls, *, transport: httpx.BaseTransport | None = None
    ) -> "FashnClient":
        return cls(settings.FASHN_API_KEY, transport=transport)

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> "FashnClient":
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def run(self, model_name: str, inputs: dict[str, Any]) -> str:
        """Submit a prediction; returns the prediction id to poll with `wait`."""
        try:
            response = self._client.post(
                "/run", json={"model_name": model_name, "inputs": inputs}
            )
        except httpx.HTTPError as exc:
            raise ExternalServiceError("fashn", "FASHN is unreachable") from exc
        if response.status_code >= 400:
            raise ExternalServiceError(
                "fashn",
                "FASHN returned an error response",
                detail={"upstream_status": response.status_code},
            )
        payload = response.json()
        prediction_id = payload.get("id") if isinstance(payload, dict) else None
        if not prediction_id:
            raise ExternalServiceError("fashn", "FASHN returned no prediction id")
        return str(prediction_id)

    def wait(
        self,
        prediction_id: str,
        *,
        timeout: float = 120.0,
        poll_interval: float = 3.0,
    ) -> list[str]:
        """Poll the prediction until it settles; returns the output CDN URLs.

        Generation takes 10-55 s. The returned URLs expire — download them
        immediately (see `download`).
        """
        deadline = time.monotonic() + timeout
        while True:
            try:
                response = self._client.get(f"/status/{prediction_id}")
            except httpx.HTTPError as exc:
                raise ExternalServiceError("fashn", "FASHN is unreachable") from exc
            if response.status_code >= 400:
                raise ExternalServiceError(
                    "fashn",
                    "FASHN returned an error response",
                    detail={"upstream_status": response.status_code},
                )
            try:
                parsed = response.json()
            except ValueError as exc:
                raise ExternalServiceError(
                    "fashn", "FASHN returned a non-JSON response"
                ) from exc
            payload = parsed if isinstance(parsed, dict) else {}
            status = str(payload.get("status") or "")
            if status == "completed":
                output = payload.get("output")
                return [str(url) for url in output] if isinstance(output, list) else []
            if status == "failed":
                raise ExternalServiceError(
                    "fashn",
                    "FASHN prediction failed",
                    detail={"error": payload.get("error")},
                )
            if status not in _PENDING_STATUSES:
                raise ExternalServiceError(
                    "fashn",
                    "FASHN returned an unexpected prediction status",
                    detail={"status": status},
                )
            if time.monotonic() >= deadline:
                raise ExternalServiceError(
                    "fashn",
                    "FASHN prediction timed out",
                    detail={"prediction_id": prediction_id, "timeout": timeout},
                )
            time.sleep(poll_interval)

    def download(self, url: str) -> bytes:
        """Fetch one output image right away (the CDN URLs expire)."""
        try:
            response = self._client.get(url)
        except httpx.HTTPError as exc:
            raise ExternalServiceError("fashn", "FASHN CDN is unreachable") from exc
        if response.status_code >= 400:
            raise ExternalServiceError(
                "fashn",
                "FASHN CDN returned an error response",
                detail={"upstream_status": response.status_code},
            )
        return response.content
