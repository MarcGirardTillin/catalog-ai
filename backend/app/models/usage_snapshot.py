"""Usage billing snapshot: frozen prices for a billed (past) month.

Once a month is billed (current date past its billing date), its prices and
coefficient must never move again — the invoice already went out. We freeze
them here (one row per account+period). Consumption itself (`usage_event`) is
append-only and immutable for a past month, so costs recomputed from a frozen
snapshot are stable; only the prices need pinning.
"""

from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import JSON, DateTime, ForeignKey, Numeric, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class UsageBillingSnapshot(Base):
    __tablename__ = "usage_billing_snapshot"

    id: Mapped[int] = mapped_column(primary_key=True)
    account_id: Mapped[int] = mapped_column(ForeignKey("account.id"), index=True)
    # Billed period, "YYYY-MM".
    period: Mapped[str] = mapped_column(String(7), index=True)
    # Coefficient frozen for this period.
    coefficient: Mapped[Decimal] = mapped_column(Numeric(16, 6))
    # Frozen unit prices: [{provider, model, metric, unit_price, currency}].
    prices_json: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
