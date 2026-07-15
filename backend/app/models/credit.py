"""Prepaid credit ledger: append-only entries, balance = SUM(credits).

One row per movement — a purchase, an admin grant, the monthly subscription
allocation, a consumption debit, or a manual adjustment. Rows are never
updated; consumption rows carry the action, quantity and unit price applied
so any past debit can be explained.
"""

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base

# kind values (validated by the schemas; kept here as the reference list).
CREDIT_KINDS = ("purchase", "grant", "subscription", "consumption", "adjustment")
# Billable actions of the credit grid (consumption entries only).
CREDIT_ACTIONS = (
    "import_product",
    "enrich_item",
    "image_process",
    "image_generate",
)


class CreditEntry(Base):
    __tablename__ = "credit_entry"
    __table_args__ = (
        Index("ix_credit_entry_account_created", "account_id", "created_at"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    account_id: Mapped[int] = mapped_column(ForeignKey("account.id"), index=True)
    kind: Mapped[str] = mapped_column(String(20))
    # Signed: positive credits the account, negative debits it.
    credits: Mapped[int] = mapped_column(default=0)
    # Consumption trace: what was consumed, how many, at which unit price.
    action: Mapped[str | None] = mapped_column(String(30), default=None)
    quantity: Mapped[int | None] = mapped_column(default=None)
    unit_credits: Mapped[int | None] = mapped_column(default=None)
    job_id: Mapped[int | None] = mapped_column(default=None)
    item_id: Mapped[int | None] = mapped_column(default=None)
    asset_id: Mapped[int | None] = mapped_column(default=None)
    # Human label for purchases/grants ("Pack 500", "Geste commercial"…).
    label: Mapped[str | None] = mapped_column(String(200), default=None)
    # "YYYY-MM" — idempotence key of the monthly subscription allocation.
    period: Mapped[str | None] = mapped_column(String(7), default=None)
    # Price actually paid for a purchase (manual bookkeeping, no Stripe).
    price_eur: Mapped[float | None] = mapped_column(default=None)
    # Admin user who recorded the entry (None for automatic consumption).
    created_by: Mapped[int | None] = mapped_column(default=None)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
