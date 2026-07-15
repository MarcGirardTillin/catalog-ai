"""Application entrypoint and FastAPI bootstrap."""

import logging
import sys
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.routing import APIRoute

from app.api.errors import handle_unexpected_exception, register_exception_handlers
from app.api.main import api_router
from app.core.config import LOG_FORMAT, settings
from app.core.db import ping_database


def configure_application_logging() -> None:
    """Configure the application logger used by backend modules."""
    level_name = str(settings.APP_LOG_LEVEL).upper()
    level = getattr(logging, level_name, logging.INFO)

    app_logger = logging.getLogger("app")
    if not app_logger.handlers:
        handler = logging.StreamHandler(stream=sys.stdout)
        handler.setFormatter(logging.Formatter(LOG_FORMAT))
        app_logger.addHandler(handler)
    app_logger.setLevel(level)
    app_logger.propagate = False


configure_application_logging()
logger = logging.getLogger(__name__)


def custom_generate_unique_id(route: APIRoute) -> str:
    """Generate stable operation ids for the OpenAPI schema."""
    return f"{route.tags[0]}-{route.name}"


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    """Validate critical startup dependencies before serving requests."""
    if not ping_database():
        raise RuntimeError("PostgreSQL is not reachable at startup")
    logger.info("Startup app")
    yield
    logger.info("Shutdown app")


app = FastAPI(
    title=settings.PROJECT_NAME,
    version=settings.APP_VERSION,
    openapi_url="/openapi.json",
    generate_unique_id_function=custom_generate_unique_id,
    lifespan=lifespan,
)


# Catch unhandled exceptions INSIDE the CORS middleware. The Exception handler
# registered below runs in Starlette's outermost ServerErrorMiddleware, whose
# response bypasses CORSMiddleware — the browser then reports a 500 as a CORS
# failure ("No 'Access-Control-Allow-Origin' header"), masking the real error
# (seen in prod on 2026-07-16). Registration order matters: CORSMiddleware is
# added AFTER this one, so it wraps it and decorates the 500 response.
@app.middleware("http")
async def _cors_safe_500(request, call_next):  # type: ignore[no-untyped-def]
    try:
        return await call_next(request)
    except Exception as exc:  # noqa: BLE001 — last-resort JSON 500
        return await handle_unexpected_exception(request, exc)


app.add_middleware(
    CORSMiddleware,
    allow_credentials=True,
    allow_headers=["*"],
    allow_methods=["*"],
    allow_origins=settings.BACKEND_CORS_ORIGIN_LIST,
    expose_headers=["Content-Disposition"],
)

register_exception_handlers(app)
app.include_router(api_router)
