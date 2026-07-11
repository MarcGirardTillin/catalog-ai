"""Application user (app-local authentication)."""

from datetime import datetime
from typing import Any

from sqlalchemy import JSON, DateTime, ForeignKey, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class User(Base):
    """A user who can sign in to CatalogAI.

    `account_id` is nullable: users created before the account table existed
    are backfilled to the default account by migration 0003.
    """

    __tablename__ = "user"

    id: Mapped[int] = mapped_column(primary_key=True)
    account_id: Mapped[int | None] = mapped_column(
        ForeignKey("account.id"), default=None, index=True
    )
    email: Mapped[str] = mapped_column(String(320), unique=True, index=True)
    hashed_password: Mapped[str] = mapped_column(String(255))
    full_name: Mapped[str | None] = mapped_column(String(255), default=None)
    is_active: Mapped[bool] = mapped_column(default=True)
    # Platform operator (admin console, pricing, cross-account monitoring).
    # Regular client users stay False — they never see providers/models/costs.
    is_admin: Mapped[bool] = mapped_column(default=False)
    # Per-user UI preferences (shortcuts, review flow, density…); None = all
    # defaults. Validated by the UserPreferences schema at the API boundary.
    preferences_json: Mapped[dict[str, Any] | None] = mapped_column(JSON, default=None)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
