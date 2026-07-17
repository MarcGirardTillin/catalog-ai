"""Request/response schemas for supplier-file import jobs and their items."""

from datetime import datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, Field

from app.imports.schema import ImportedProduct


class ImportJobCounts(BaseModel):
    total: int = 0
    ready_for_review: int = 0  # à transférer (non écarté, non transféré)
    applied: int = 0  # déjà transféré vers Tillin
    rejected: int = 0  # écarté (ne sera pas transféré)
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
    # First uploaded file name (kept for the existing single-name frontend).
    file_name: str
    # Every uploaded file name, in order (multi-file imports).
    file_names: list[str] = Field(default_factory=list)
    counts: ImportJobCounts
    totals: ImportJobTotals = Field(default_factory=ImportJobTotals)
    # Document-level facts read from the file (purchase orders mostly).
    po_number: str | None = None
    supplier: str | None = None
    # Selected import profile (config_json["profile_id"]), None when unset.
    profile_id: int | None = None
    # Target Tillin location (config_json["location_id"]), None when unset.
    location_id: int | None = None
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
    # Tillin product id once linked back after transfer (by reference_code).
    tillin_product_id: int | None = None
    # Typed as the frozen import contract so the generated frontend client
    # carries the real product/variant shape (not an opaque dict).
    payload: ImportedProduct
    warnings: list[str] = Field(default_factory=list)
    error: str | None = None
    created_at: datetime


class ImportLinkResult(BaseModel):
    """POST /imports/{id}/link-products outcome (resolution by reference)."""

    linked: int = 0
    already_linked: int = 0
    not_found: list[str] = Field(default_factory=list)  # unresolved refs


class ImportReconcileResult(BaseModel):
    """POST /imports/{id}/reconcile outcome (lost-transfer recovery).

    Each still-transferable item is looked up in Tillin by reference:
    found → marked `applied` + linked; not found → left as-is.
    """

    checked: int = 0
    applied: int = 0
    not_found: list[str] = Field(default_factory=list)  # unresolved refs


class ImportProductLine(BaseModel):
    """One row of the « Par import » products view (local data only)."""

    item_id: int
    status: str
    supplier_ref: str
    title: str | None = None
    brand: str | None = None
    image_url: str | None = None
    variant_count: int = 0
    tillin_product_id: int | None = None


class ImportProducts(BaseModel):
    import_id: int
    file_name: str
    items: list[ImportProductLine] = Field(default_factory=list)
    linked_count: int = 0
    unlinked_count: int = 0


class ImportItemUpdate(BaseModel):
    """Review edits: a corrected payload and/or a reject/restore status."""

    # Typed as the frozen import contract (validated by pydantic at the
    # boundary; the route re-normalizes before storing).
    payload: ImportedProduct | None = None
    # Only "ready_for_review" (restore) and "rejected" are accepted.
    status: str | None = None


class ImportItemsBulkUpdate(BaseModel):
    """PATCH /imports/{id}/items body — one-shot include/exclude of many items.

    Powers « tout transférer / tout écarter » in one request instead of one
    PATCH per item (atomic, and fast on 100+ product imports).
    """

    ids: list[int] = Field(min_length=1)
    # Only "ready_for_review" (include) and "rejected" (exclude) are accepted.
    status: str


class ImportItemsBulkResult(BaseModel):
    # Items actually changed (already-target / non-editable ones are skipped).
    updated: int = 0
    counts: ImportJobCounts


class ImportProfileSelection(BaseModel):
    """PUT /imports/{id}/profile body — null clears the selection."""

    profile_id: int | None


class ImportLocationSelection(BaseModel):
    """PUT /imports/{id}/location body — null clears the selection."""

    location_id: int | None


class ImportRenderPreview(BaseModel):
    """JSON preview of the rendered Tillin import CSV."""

    columns: list[str]
    rows: list[list[str]]
    warnings: list[str] = Field(default_factory=list)
    row_count: int = 0


class ImportTransferRequest(BaseModel):
    """POST /imports/{id}/transfer body.

    A null location falls back to the job's selected location
    (config_json["location_id"]); missing both is a 400 `location_required`.
    """

    location_id: int | None = None
    profile_id: int | None = None
    # Créer la réception dans Tillin : décoché = toutes les quantités du
    # fichier de transfert sont mises à zéro (fiches créées sans stock).
    create_reception: bool = True


class ImportTransferResult(BaseModel):
    ok: bool = True
    row_count: int = 0
