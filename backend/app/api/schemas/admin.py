"""Admin console schemas: cross-account monitoring (operator only).

Everything here is served exclusively under CurrentAdminDep — it carries the
white-label-sensitive numbers (raw cost vs billable = the operator's margin).
"""

from datetime import datetime

from pydantic import BaseModel


class AdminAccountSummary(BaseModel):
    """One row of the accounts list."""

    id: int
    name: str
    user_count: int
    created_at: datetime
    # Latest activity, any type (None = account never ran anything).
    last_activity_at: datetime | None


class AdminOverviewLine(BaseModel):
    """Per-account monthly monitoring line (money as decimal strings)."""

    account_id: int
    account_name: str
    cost: str  # raw provider cost
    billable: str  # invoiced to the client (cost × coefficient)
    margin: str  # billable - cost
    coefficient: float
    jobs_count: int  # enrichment jobs created this month
    imports_count: int  # import jobs created this month
    failed_items: int  # failed items (both types) on this month's jobs


class AdminOverview(BaseModel):
    month: str
    currency: str
    lines: list[AdminOverviewLine]


class AdminActivityEntry(BaseModel):
    """One recent job/import of an account (monitoring feed)."""

    job_id: int
    job_type: str  # "enrichment" | "import"
    label: str
    status: str
    total_items: int
    failed_items: int
    created_at: datetime


class AdminAccountActivity(BaseModel):
    account_id: int
    entries: list[AdminActivityEntry]
