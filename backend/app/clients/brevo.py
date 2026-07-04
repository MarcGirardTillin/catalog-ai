"""Brevo client — "job finished" notification emails (non-blocking by design)."""

import logging

import httpx

from app.clients.base import ExternalServiceError, NotConfiguredError
from app.core.config import settings

logger = logging.getLogger(__name__)

BASE_URL = "https://api.brevo.com"


class BrevoClient:
    def __init__(
        self,
        api_key: str,
        *,
        sender_email: str,
        sender_name: str = "CatalogAI",
        timeout: float = 30.0,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        if not api_key or not sender_email:
            raise NotConfiguredError("brevo")
        self._sender = {"email": sender_email, "name": sender_name}
        self._client = httpx.Client(
            base_url=BASE_URL,
            headers={"api-key": api_key},
            timeout=timeout,
            transport=transport,
        )

    @classmethod
    def from_settings(
        cls, *, transport: httpx.BaseTransport | None = None
    ) -> "BrevoClient":
        return cls(
            settings.BREVO_API_KEY,
            sender_email=settings.BREVO_SENDER_EMAIL,
            sender_name=settings.BREVO_SENDER_NAME,
            transport=transport,
        )

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> "BrevoClient":
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def send_email(self, *, to: str, subject: str, html: str) -> str | None:
        """Send one transactional email; returns the Brevo message id."""
        try:
            response = self._client.post(
                "/v3/smtp/email",
                json={
                    "sender": self._sender,
                    "to": [{"email": to}],
                    "subject": subject,
                    "htmlContent": html,
                },
            )
        except httpx.HTTPError as exc:
            raise ExternalServiceError("brevo", "Brevo is unreachable") from exc
        if response.status_code >= 400:
            raise ExternalServiceError(
                "brevo",
                "Brevo returned an error response",
                detail={"upstream_status": response.status_code},
            )
        message_id = response.json().get("messageId")
        logger.info("Notification email sent to %s (%s)", to, message_id)
        return str(message_id) if message_id else None
