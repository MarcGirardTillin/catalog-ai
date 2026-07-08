"""Dashboard statistics schema."""

from pydantic import BaseModel


class DashboardStats(BaseModel):
    """Account-scoped headline numbers for the dashboard KPI row."""

    applied_items: int = 0
    ready_items: int = 0
    running_jobs: int = 0
    jobs_total: int = 0
    items_total: int = 0
    # Average per-item processing time over settled items, in seconds.
    avg_item_seconds: float | None = None
    # Share of settled items whose source page was resolved automatically
    # (0..1); None when nothing has been processed yet.
    auto_resolve_rate: float | None = None
