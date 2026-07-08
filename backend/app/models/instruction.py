"""Named editorial instruction templates (per-account library).

A template can claim Tillin category names (``categories_json``): it then
becomes the default instruction for products of those categories when a job
doesn't pin instructions explicitly. Jobs snapshot the content at creation
time, so editing/deleting a template never changes past jobs.
"""

from datetime import datetime
from typing import Any

from sqlalchemy import JSON, DateTime, ForeignKey, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class InstructionTemplate(Base):
    __tablename__ = "instruction_template"

    id: Mapped[int] = mapped_column(primary_key=True)
    account_id: Mapped[int] = mapped_column(ForeignKey("account.id"), index=True)
    name: Mapped[str] = mapped_column(String(120))
    content: Mapped[str] = mapped_column(Text)
    # Tillin category names this instruction is the default for; None/[] = none.
    categories_json: Mapped[list[Any] | None] = mapped_column(JSON, default=None)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
