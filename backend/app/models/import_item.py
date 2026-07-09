"""Import staging: one row per product extracted from a supplier file.

An import job (enrichment_job with job_type="import") parses the uploaded
file and stages one `import_item` per extracted product. The payload is the
frozen contract's `ImportedProduct.model_dump(mode="json")` (see
`app/imports/schema.py`); review/apply semantics come in later lots.
"""

from datetime import datetime
from typing import Any

from sqlalchemy import JSON, DateTime, ForeignKey, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base

IMPORT_ITEM_STATUSES = ("ready_for_review", "approved", "applied", "rejected", "failed")


class ImportItem(Base):
    __tablename__ = "import_item"

    id: Mapped[int] = mapped_column(primary_key=True)
    job_id: Mapped[int] = mapped_column(ForeignKey("enrichment_job.id"), index=True)
    account_id: Mapped[int] = mapped_column(ForeignKey("account.id"), index=True)
    status: Mapped[str] = mapped_column(String(20), default="ready_for_review")
    # Tillin product id once the transferred item is linked back to the
    # created product (resolved by reference_code — /product_import returns
    # no ids). Xano-side id: no FK.
    tillin_product_id: Mapped[int | None] = mapped_column(default=None)
    # ImportedProduct.model_dump(mode="json") — the extracted product.
    payload_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    # Product-level extraction warnings surfaced in the review UI.
    warnings_json: Mapped[list[Any] | None] = mapped_column(JSON, default=None)
    error: Mapped[str | None] = mapped_column(Text, default=None)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
