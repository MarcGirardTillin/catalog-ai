"""Leg A persistence: enrichment jobs and their per-product items.

State machines (see plan):
- job:  pending -> processing -> completed | partial | failed
- item: pending -> processing -> ready_for_review
        -> (approved -> applied) | rejected | failed
"""

from datetime import datetime
from typing import Any

from sqlalchemy import JSON, DateTime, ForeignKey, Index, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base

JOB_STATUSES = ("pending", "processing", "completed", "partial", "failed")
ITEM_STATUSES = (
    "pending",
    "processing",
    "ready_for_review",
    "approved",
    "applied",
    "rejected",
    "failed",
)
MAX_ATTEMPTS = 3


class EnrichmentJob(Base):
    __tablename__ = "enrichment_job"

    id: Mapped[int] = mapped_column(primary_key=True)
    account_id: Mapped[int] = mapped_column(ForeignKey("account.id"), index=True)
    status: Mapped[str] = mapped_column(String(20), default="pending", index=True)
    # "enrichment" (catalog enrichment run) or "import" (supplier file import).
    # Import jobs reference their uploaded file in selection_json:
    # {"file_name": str, "file_path": str}.
    job_type: Mapped[str] = mapped_column(
        String(20), default="enrichment", server_default="enrichment"
    )
    # {"ids": [...]} or {"tag": "..."} — the product selection as submitted.
    selection_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    # Transform toggles, templates, ai/scrape/source settings (plan: config_json).
    config_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    # Set when the first item leaves the queue / when the last one settles, so
    # we can report how long the run actually took (started -> finished).
    started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), default=None
    )
    finished_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), default=None
    )

    items: Mapped[list["EnrichmentItem"]] = relationship(
        back_populates="job", cascade="all, delete-orphan"
    )


class EnrichmentItem(Base):
    __tablename__ = "enrichment_item"
    __table_args__ = (
        # Worker queue scan: claim pending items in insertion order.
        Index("ix_enrichment_item_status_id", "status", "id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    job_id: Mapped[int] = mapped_column(ForeignKey("enrichment_job.id"), index=True)
    account_id: Mapped[int] = mapped_column(ForeignKey("account.id"), index=True)
    tillin_product_id: Mapped[int] = mapped_column()
    status: Mapped[str] = mapped_column(String(20), default="pending")

    source_url: Mapped[str | None] = mapped_column(String(2048), default=None)
    source_method: Mapped[str | None] = mapped_column(String(30), default=None)
    match_score: Mapped[float | None] = mapped_column(default=None)
    # Why resolution landed where it did: {"reason": str|None,
    # "candidates": [{"url","title","score"}]} — powers the manual-resolve UI.
    resolution_json: Mapped[dict[str, Any] | None] = mapped_column(JSON, default=None)

    staged_title: Mapped[str | None] = mapped_column(String(500), default=None)
    staged_description: Mapped[str | None] = mapped_column(default=None)
    staged_meta: Mapped[str | None] = mapped_column(String(500), default=None)
    staged_images_json: Mapped[list[Any] | None] = mapped_column(JSON, default=None)
    staged_weights_json: Mapped[list[Any] | None] = mapped_column(JSON, default=None)
    # Reviewer's per-field keep/drop choices for the apply step, e.g.
    # {"title": false, "images": true}. Missing key or None = apply the field.
    apply_fields_json: Mapped[dict[str, Any] | None] = mapped_column(JSON, default=None)

    error: Mapped[str | None] = mapped_column(default=None)
    attempt_count: Mapped[int] = mapped_column(default=0)
    # Per-item processing window: claim -> settled (reset on each new claim).
    started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), default=None
    )
    finished_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), default=None
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    job: Mapped[EnrichmentJob] = relationship(back_populates="items")
