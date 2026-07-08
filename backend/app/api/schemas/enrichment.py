"""Request/response schemas for enrichment jobs and items."""

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field, model_validator


class JobSelection(BaseModel):
    """Product selection: explicit Tillin ids or a tag (exactly one)."""

    ids: list[int] | None = None
    tag: str | None = None

    @model_validator(mode="after")
    def _exactly_one(self) -> "JobSelection":
        if (self.ids is None or len(self.ids) == 0) == (self.tag is None):
            raise ValueError("Provide exactly one of 'ids' or 'tag'")
        return self


class JobCreateRequest(BaseModel):
    selection: JobSelection
    config: dict[str, Any] = Field(default_factory=dict)


class JobCounts(BaseModel):
    total: int = 0
    pending: int = 0
    processing: int = 0
    ready_for_review: int = 0
    approved: int = 0
    applied: int = 0
    rejected: int = 0
    failed: int = 0


class JobPublic(BaseModel):
    id: int
    status: str
    selection_json: dict[str, Any]
    config_json: dict[str, Any]
    counts: JobCounts
    created_at: datetime
    started_at: datetime | None = None
    finished_at: datetime | None = None
    # Wall-clock processing time in seconds, once the run has settled.
    duration_seconds: float | None = None


class ItemPublic(BaseModel):
    id: int
    job_id: int
    tillin_product_id: int
    status: str
    source_url: str | None = None
    source_method: str | None = None
    match_score: float | None = None
    resolution_json: dict[str, Any] | None = None
    staged_title: str | None = None
    staged_description: str | None = None
    staged_meta: str | None = None
    staged_images_json: list[Any] | None = None
    staged_weights_json: list[Any] | None = None
    error: str | None = None
    attempt_count: int
    started_at: datetime | None = None
    finished_at: datetime | None = None
    # Wall-clock processing time in seconds, once the item has settled.
    duration_seconds: float | None = None
    updated_at: datetime

    @model_validator(mode="after")
    def _compute_duration(self) -> "ItemPublic":
        if self.started_at is not None and self.finished_at is not None:
            self.duration_seconds = (
                self.finished_at - self.started_at
            ).total_seconds()
        return self


class ItemPatchRequest(BaseModel):
    """Editable staged fields (review-time corrections)."""

    staged_title: str | None = None
    staged_description: str | None = None
    staged_meta: str | None = None
    staged_images_json: list[Any] | None = None
    staged_weights_json: list[Any] | None = None


class ItemResolveRequest(BaseModel):
    """Manually point an item at a specific source product page."""

    source_url: str = Field(min_length=1)

    @model_validator(mode="after")
    def _looks_like_product_url(self) -> "ItemResolveRequest":
        if "/products/" not in self.source_url:
            raise ValueError("Expected a Shopify product URL (…/products/<handle>)")
        return self
