"""Imaging sprint persistence: one row per à-la-carte image operation.

One table, three jobs: async task tracking (the generative verb runs in a
FastAPI BackgroundTask), provenance trace (provider + model + seed + params)
and audit (which Tillin images were created / replaced).

State machine: pending -> processing -> completed | failed, then
completed/failed -> discarded when the user dismisses an unsaved result
(the row is kept for the generation history; the staging is purged).
"""

from datetime import datetime
from typing import Any

from sqlalchemy import JSON, DateTime, ForeignKey, Index, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base

ASSET_STATUSES = ("pending", "processing", "completed", "failed", "discarded")


class ImageAsset(Base):
    __tablename__ = "image_asset"
    __table_args__ = (
        Index("ix_image_asset_product_id", "product_id"),
        Index("ix_image_asset_status", "status"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    account_id: Mapped[int] = mapped_column(ForeignKey("account.id"))
    # Tillin (Xano) product id — external system, no FK on purpose.
    product_id: Mapped[int] = mapped_column()
    # Business verb: "normalize" | "generate_model" | ...
    verb: Mapped[str] = mapped_column(String(30))
    provider: Mapped[str] = mapped_column(String(20))  # "photoroom" | "fashn" | ...
    model: Mapped[str | None] = mapped_column(String(80), default=None)
    seed: Mapped[int | None] = mapped_column(default=None)
    # Options + trace params the operation ran with (reproducibility/audit).
    params_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    status: Mapped[str] = mapped_column(String(20), default="pending")
    # URL or reference of the source image the verb consumed.
    source_image: Mapped[str | None] = mapped_column(String(1000), default=None)
    # Tillin `product_image` id of the original (for the replace-on-save flow).
    source_product_image_id: Mapped[int | None] = mapped_column(default=None)
    # Staging-relative paths of the produced files (see app.imaging.staging).
    staged_paths_json: Mapped[list[Any]] = mapped_column(JSON, default=list)
    # Staged files metadata, one entry per file: {role: source|cutout|output,
    # path, bytes, width, height, format, index}. The cutout entry is what
    # re-renders recompose from. NULL on legacy assets (fallback on
    # staged_paths_json).
    staged_files_json: Mapped[list[Any] | None] = mapped_column(JSON, default=None)
    # Tillin `product_image` ids created at save time (None = not saved yet).
    tillin_image_ids_json: Mapped[list[Any] | None] = mapped_column(JSON, default=None)
    error: Mapped[str | None] = mapped_column(default=None)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    finished_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), default=None
    )
