import logging
from collections.abc import Awaitable, Callable
from typing import Any, cast

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.responses import Response

from app.api.exceptions import AppException
from app.api.schemas import ApiError

logger = logging.getLogger(__name__)
ExceptionHandler = Callable[[Request, Exception], Response | Awaitable[Response]]


def _error_response(
    *,
    status_code: int,
    code: str,
    message: str,
    detail: Any | None = None,
) -> JSONResponse:
    payload = ApiError(code=code, message=message, detail=detail)
    return JSONResponse(status_code=status_code, content=payload.model_dump())


async def handle_app_exception(_: Request, exc: AppException) -> JSONResponse:
    return _error_response(
        status_code=exc.status_code,
        code=exc.code,
        message=exc.message,
        detail=exc.detail,
    )


async def handle_http_exception(_: Request, exc: HTTPException) -> JSONResponse:
    detail = exc.detail
    message = detail if isinstance(detail, str) else "HTTP error"
    return _error_response(
        status_code=exc.status_code,
        code="http_error",
        message=message,
        detail=detail,
    )


async def handle_validation_exception(
    _: Request, exc: RequestValidationError
) -> JSONResponse:
    return _error_response(
        status_code=422,
        code="validation_error",
        message="Request validation failed",
        detail=exc.errors(),
    )


async def handle_unexpected_exception(_: Request, exc: Exception) -> JSONResponse:
    logger.exception("Unhandled application error: %s", exc)
    return _error_response(
        status_code=500,
        code="internal_server_error",
        message="Internal server error",
        detail=None,
    )


def register_exception_handlers(app: FastAPI) -> None:
    app.add_exception_handler(
        AppException, cast("ExceptionHandler", handle_app_exception)
    )
    app.add_exception_handler(
        HTTPException, cast("ExceptionHandler", handle_http_exception)
    )
    app.add_exception_handler(
        RequestValidationError, cast("ExceptionHandler", handle_validation_exception)
    )
    app.add_exception_handler(
        Exception, cast("ExceptionHandler", handle_unexpected_exception)
    )
