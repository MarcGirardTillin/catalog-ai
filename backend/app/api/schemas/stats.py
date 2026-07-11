"""Dashboard statistics schema."""

from pydantic import BaseModel


class DashboardStats(BaseModel):
    """Account-scoped headline numbers for the dashboard.

    Server-side exact counters (the frontend previously approximated some of
    these from the first page of paginated lists).
    """

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

    # --- « À traiter » (actionable counters, all types) ---
    # Import products awaiting transfer to Tillin (import_item ready_for_review).
    imports_to_transfer: int = 0
    # Import analyses still running (import jobs pending/processing).
    imports_processing: int = 0
    # Failed items, enrichment + import combined.
    failed_items: int = 0

    # --- « Ce mois-ci » (current UTC month) ---
    # Enrichment items applied to Tillin, created this month.
    applied_this_month: int = 0
    # Import products transferred to Tillin, created this month.
    imported_this_month: int = 0
    # imported × minutes_saved_per_import_product +
    # applied × minutes_saved_per_enriched_product (account settings).
    minutes_saved_this_month: int = 0
