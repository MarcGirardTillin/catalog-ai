"""Usage reporting schemas: price CRUD, monthly summary, per-job breakdown.

Money values travel as strings (Decimal serialized) so no float rounding ever
leaks into what the client bills. `None` means "no price configured".
"""

from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, Field


class UsagePriceCreate(BaseModel):
    provider: str = Field(min_length=1, max_length=20)
    model: str | None = Field(None, max_length=80)
    metric: str = Field(min_length=1, max_length=30)
    unit_price: Decimal = Field(ge=0)
    currency: str = Field("EUR", min_length=3, max_length=3)


class UsagePriceUpdate(BaseModel):
    provider: str | None = Field(None, min_length=1, max_length=20)
    model: str | None = Field(None, max_length=80)
    metric: str | None = Field(None, min_length=1, max_length=30)
    unit_price: Decimal | None = Field(None, ge=0)
    currency: str | None = Field(None, min_length=3, max_length=3)


class UsagePricePublic(BaseModel):
    id: int
    provider: str
    model: str | None
    metric: str
    unit_price: str  # Decimal serialized as string
    currency: str


class UsageSummaryLine(BaseModel):
    provider: str
    model: str | None
    metric: str
    quantity: int
    unit_price: str | None  # null = no price configured
    cost: str | None
    billable: str | None


class UsageTotals(BaseModel):
    cost: str
    billable: str


class UsageSummary(BaseModel):
    month: str  # "YYYY-MM"
    currency: str
    coefficient: float
    lines: list[UsageSummaryLine]
    totals: UsageTotals
    unpriced_count: int
    # Billing/freeze status of the month (see usage_billing_snapshot).
    frozen: bool = False  # True once the month has been billed (prices pinned)
    billing_date: str  # "YYYY-MM-DD": the day this month is/was billed
    frozen_at: datetime | None = None  # when the snapshot was taken


class UsageTimeseriesPoint(BaseModel):
    date: str  # "YYYY-MM-DD"
    amount: str  # billable (EUR), Decimal serialized; "0" when unpriced
    quantity: int  # raw metric quantity summed for this series/day


class UsageTimeseriesSeries(BaseModel):
    # "total" for group_by=none; a model name or provider name otherwise.
    key: str
    points: list[UsageTimeseriesPoint]


class UsageTimeseries(BaseModel):
    month: str
    group_by: str  # "none" | "model" | "provider"
    currency: str
    series: list[UsageTimeseriesSeries]


class UsageJobMetric(BaseModel):
    provider: str
    metric: str
    quantity: int


class UsageJobLine(BaseModel):
    job_id: int | None  # null = events recorded outside any job
    job_type: str | None
    label: str
    created_at: datetime | None
    input_tokens: int
    output_tokens: int
    other_metrics: list[UsageJobMetric]
    cost: str | None  # null when NO metric of the job is priced
    billable: str | None


class UsageByJob(BaseModel):
    month: str
    jobs: list[UsageJobLine]
