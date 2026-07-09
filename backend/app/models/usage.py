"""Usage metering (M1): append-only ledger of billable consumption events.

One row per (metric, quantity) pair — e.g. a Claude call writes one
`input_tokens` row and one `output_tokens` row. This is the raw material for
client-facing usage reporting and future billing; rows are never updated.
"""

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class UsageEvent(Base):
    __tablename__ = "usage_event"

    id: Mapped[int] = mapped_column(primary_key=True)
    account_id: Mapped[int] = mapped_column(ForeignKey("account.id"), index=True)
    job_id: Mapped[int | None] = mapped_column(
        ForeignKey("enrichment_job.id"), default=None, index=True
    )
    # Item id in the source-specific item table (enrichment_item or
    # import_item, per `source`) — no FK on purpose.
    item_id: Mapped[int | None] = mapped_column(default=None)
    source: Mapped[str] = mapped_column(String(20))  # "enrichment" | "import" | ...
    provider: Mapped[str] = mapped_column(String(20))  # "claude" | ...
    model: Mapped[str | None] = mapped_column(String(80), default=None)
    metric: Mapped[str] = mapped_column(String(30))  # "input_tokens" | ...
    quantity: Mapped[int] = mapped_column(default=0)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
