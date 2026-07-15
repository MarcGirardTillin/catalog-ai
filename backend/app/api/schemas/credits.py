"""Credit schemas: client overview, timeseries, admin ledger + grant."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

from app.api.schemas.settings import CreditPack

CreditKind = Literal["purchase", "grant", "subscription", "consumption", "adjustment"]
CreditAction = Literal[
    "import_product", "enrich_item", "image_process", "image_generate"
]


class CreditEntryPublic(BaseModel):
    id: int
    kind: CreditKind
    credits: int
    action: CreditAction | None = None
    quantity: int | None = None
    unit_credits: int | None = None
    job_id: int | None = None
    item_id: int | None = None
    asset_id: int | None = None
    label: str | None = None
    period: str | None = None
    price_eur: float | None = None
    created_at: datetime


class CreditMonth(BaseModel):
    """Consumption aggregates of one month."""

    month: str
    consumed_total: int = 0
    by_action: dict[str, int] = Field(default_factory=dict)


class CreditOverview(BaseModel):
    """Client view: balance, thresholds, packs and the month's movements."""

    balance: int
    low_credit_threshold: int
    monthly_free_credits: int
    packs: list[CreditPack] = Field(default_factory=list)
    month: CreditMonth
    # Month movements that are NOT consumption (purchases, grants, allocation);
    # daily consumption is served by /credits/timeseries.
    entries: list[CreditEntryPublic] = Field(default_factory=list)


class CreditTimeseriesPoint(BaseModel):
    date: str
    credits: int = 0


class CreditTimeseriesSeries(BaseModel):
    key: str
    points: list[CreditTimeseriesPoint]


class CreditTimeseries(BaseModel):
    month: str
    series: list[CreditTimeseriesSeries]


class AdminCredits(BaseModel):
    """Admin view of one account's credits: balance + recent ledger."""

    balance: int
    entries: list[CreditEntryPublic]


class CreditGrantRequest(BaseModel):
    """Manual ledger entry recorded by the operator (grant/purchase/fix)."""

    credits: int = Field(description="Signed amount: positive credits, negative debits")
    kind: Literal["grant", "purchase", "adjustment"] = "grant"
    label: str | None = Field(default=None, max_length=200)
    price_eur: float | None = Field(default=None, ge=0)
