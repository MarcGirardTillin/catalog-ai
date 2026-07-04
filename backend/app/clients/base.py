"""Shared error types for external service clients."""

from typing import Any

from app.api.exceptions import AppException


class ExternalServiceError(AppException):
    """An upstream external service failed."""

    def __init__(
        self,
        service: str,
        message: str,
        *,
        status_code: int = 502,
        detail: Any | None = None,
    ) -> None:
        super().__init__(
            status_code=status_code,
            code=f"{service}_error",
            message=message,
            detail=detail,
        )


class NotConfiguredError(AppException):
    """The client's API key/settings are missing — integration disabled."""

    def __init__(self, service: str) -> None:
        super().__init__(
            status_code=503,
            code=f"{service}_not_configured",
            message=f"{service} integration is not configured",
        )
