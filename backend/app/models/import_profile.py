"""Import profile: per-(account, supplier) conventions applied at render time.

A profile turns raw extracted facts (`import_item.payload_json`) into Tillin
import CSV rows: pricing rule, barcode rule, brand rule, fixed labels
(supplier, season), defaults (tax rate, status, gender). The rule shapes are
frozen in `app.api.schemas.import_profiles.ImportProfileConfig`.
"""

from datetime import datetime
from typing import Any

from sqlalchemy import JSON, DateTime, ForeignKey, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class ImportProfile(Base):
    __tablename__ = "import_profile"

    id: Mapped[int] = mapped_column(primary_key=True)
    account_id: Mapped[int] = mapped_column(ForeignKey("account.id"), index=True)
    # Display name, e.g. "L'Espion" or "Bambinoh — Garcia".
    name: Mapped[str] = mapped_column(String(120))
    # Lowercased supplier name used to auto-suggest the profile when it
    # matches the extracted document supplier ("" = never auto-matched).
    supplier_match: Mapped[str] = mapped_column(String(120), default="")
    # ImportProfileConfig.model_dump() — the frozen rule shapes.
    config_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
