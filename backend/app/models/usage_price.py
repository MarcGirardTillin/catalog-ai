"""Usage pricing (M3): per-account unit prices for usage_event metrics.

Costs are NEVER stored on the events themselves — they are computed at read
time from this table, so repricing is always possible. Resolution order for an
event: exact (provider, model, metric) first, then the provider-wide fallback
(provider, model IS NULL, metric), else no price (cost is null).
"""

from datetime import datetime
from decimal import Decimal

from sqlalchemy import DateTime, ForeignKey, Numeric, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class UsagePrice(Base):
    __tablename__ = "usage_price"

    id: Mapped[int] = mapped_column(primary_key=True)
    account_id: Mapped[int] = mapped_column(ForeignKey("account.id"), index=True)
    provider: Mapped[str] = mapped_column(String(20))  # "claude" | ...
    # None = applies to every model of the provider (fallback price).
    model: Mapped[str | None] = mapped_column(String(80), default=None)
    metric: Mapped[str] = mapped_column(String(30))  # "input_tokens" | ...
    # Price PER UNIT, e.g. 0.000003 €/token for 3 €/M tokens.
    unit_price: Mapped[Decimal] = mapped_column(Numeric(16, 10))
    currency: Mapped[str] = mapped_column(String(3), default="EUR")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
