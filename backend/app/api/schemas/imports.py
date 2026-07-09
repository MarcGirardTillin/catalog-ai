"""Request/response schemas for supplier-file import jobs and their items."""

from datetime import datetime
from decimal import Decimal
from typing import Any, Literal

from pydantic import BaseModel, Field


class ImportJobCounts(BaseModel):
    total: int = 0
    ready_for_review: int = 0
    failed: int = 0


class ImportJobTotals(BaseModel):
    """Aggregates over every extracted variant (a missing quantity counts
    as 1 unit; amounts are quantity x unit price, None when no price at all)."""

    quantity: int = 0
    wholesale_amount: Decimal | None = None
    retail_amount: Decimal | None = None


class ImportJobPublic(BaseModel):
    id: int
    status: str
    file_name: str
    counts: ImportJobCounts
    totals: ImportJobTotals = Field(default_factory=ImportJobTotals)
    # Document-level facts read from the file (purchase orders mostly).
    po_number: str | None = None
    supplier: str | None = None
    warnings: list[str] = Field(default_factory=list)
    error: str | None = None
    created_at: datetime
    started_at: datetime | None = None
    finished_at: datetime | None = None
    # Wall-clock processing time in seconds (finished - started), once settled.
    duration_seconds: float | None = None


class ImportFilePreviewSheet(BaseModel):
    sheet: str | None = None
    # First rows of the sheet, capped (see routes) — cells are plain strings.
    rows: list[list[str]] = Field(default_factory=list)
    total_rows: int = 0
    truncated: bool = False


class ImportFilePreview(BaseModel):
    kind: Literal["pdf", "tabular"]
    file_name: str
    # Empty for PDFs — the frontend renders those from GET /imports/{id}/file.
    sheets: list[ImportFilePreviewSheet] = Field(default_factory=list)


class ImportItemPublic(BaseModel):
    id: int
    status: str
    # ImportedProduct.model_dump(mode="json") — see app/imports/schema.py.
    payload: dict[str, Any]
    warnings: list[str] = Field(default_factory=list)
    error: str | None = None
    created_at: datetime
