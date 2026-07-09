"""Request/response schemas for supplier-file import jobs and their items."""

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class ImportJobCounts(BaseModel):
    total: int = 0
    ready_for_review: int = 0
    failed: int = 0


class ImportJobPublic(BaseModel):
    id: int
    status: str
    file_name: str
    counts: ImportJobCounts
    warnings: list[str] = Field(default_factory=list)
    error: str | None = None
    created_at: datetime
    started_at: datetime | None = None
    finished_at: datetime | None = None
    # Wall-clock processing time in seconds (finished - started), once settled.
    duration_seconds: float | None = None


class ImportItemPublic(BaseModel):
    id: int
    status: str
    # ImportedProduct.model_dump(mode="json") — see app/imports/schema.py.
    payload: dict[str, Any]
    warnings: list[str] = Field(default_factory=list)
    error: str | None = None
    created_at: datetime
