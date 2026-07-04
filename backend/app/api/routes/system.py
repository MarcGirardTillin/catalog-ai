"""Public system endpoints used for health and runtime metadata."""

from typing import Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.core.config import settings
from app.core.db import ping_database

router = APIRouter(tags=["system"])


class HealthResponse(BaseModel):
    """Response returned by the healthcheck endpoint."""

    status: Literal["ok"]
    database: Literal["up"]


class VersionResponse(BaseModel):
    """Response exposing the running application version metadata."""

    app: str
    version: str
    build: str | None = None
    commit: str | None = None
    branch: str | None = None
    environment: str


@router.get("/healthcheck", response_model=HealthResponse)
def healthcheck() -> HealthResponse:
    """Return backend health only when PostgreSQL is reachable."""
    if not ping_database():
        raise HTTPException(status_code=503, detail="Database unavailable")
    return HealthResponse(status="ok", database="up")


@router.get("/version", response_model=VersionResponse)
def version() -> VersionResponse:
    """Return application version and runtime metadata."""
    return VersionResponse(
        app=settings.PROJECT_NAME,
        version=settings.APP_VERSION,
        build=settings.APP_BUILD,
        commit=settings.APP_COMMIT_SHA,
        branch=settings.APP_BRANCH,
        environment=settings.ENVIRONMENT,
    )
