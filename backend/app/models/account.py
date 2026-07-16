"""Tenancy root: every business table is scoped by `account_id`.

One account per Tillin company (`xano_company_id`), resolved at login from
Xano's `/auth/me`. The historical default account (NULL company) remains for
app-local users — operator/dev logins that never went through Xano.
"""

from datetime import datetime
from typing import Any

from sqlalchemy import JSON, DateTime, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base

DEFAULT_ACCOUNT_NAME = "default"


class Account(Base):
    __tablename__ = "account"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(255), unique=True)
    # Tillin company id (Xano `/auth/me` -> `company`). One account per
    # company; NULL for the legacy default account (app-local users only).
    xano_company_id: Mapped[int | None] = mapped_column(
        default=None, unique=True, index=True
    )
    # Boutique-level enrichment defaults (title template, editorial
    # instructions, notifications…); None = all defaults. Validated by the
    # AccountSettings schema at the API boundary.
    settings_json: Mapped[dict[str, Any] | None] = mapped_column(JSON, default=None)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
