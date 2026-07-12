"""Dashboard statistics route."""

from datetime import UTC, datetime

from fastapi import APIRouter
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.deps import CurrentUserDep, SessionDep
from app.api.schemas.settings import AccountSettings
from app.api.schemas.stats import DashboardStats
from app.api.services.accounts import resolve_account_id
from app.models import Account, EnrichmentItem, EnrichmentJob, ImportItem

router = APIRouter(prefix="/stats", tags=["stats"])

# Items the worker has finished with (mirrors app.jobs.queue._WORKER_TERMINAL).
_SETTLED = ("ready_for_review", "approved", "applied", "rejected", "failed")
# source_method values that mean "the source page was found without a human".
_AUTO_METHODS = ("shopify_json",)


def _dashboard_stats(db: Session, account_id: int) -> DashboardStats:
    item_counts = dict(
        db.execute(
            select(EnrichmentItem.status, func.count())
            .where(EnrichmentItem.account_id == account_id)
            .group_by(EnrichmentItem.status)
        )
        .tuples()
        .all()
    )
    # Per (job_type, status): the dashboard separates enrichments from imports.
    job_counts_typed: dict[tuple[str, str], int] = {
        (job_type, status): count
        for job_type, status, count in db.execute(
            select(EnrichmentJob.job_type, EnrichmentJob.status, func.count())
            .where(EnrichmentJob.account_id == account_id)
            .group_by(EnrichmentJob.job_type, EnrichmentJob.status)
        )
        .tuples()
        .all()
    }
    job_counts: dict[str, int] = {}
    for (job_type, status), count in job_counts_typed.items():
        if job_type == "enrichment":
            job_counts[status] = job_counts.get(status, 0) + count
    import_item_counts = dict(
        db.execute(
            select(ImportItem.status, func.count())
            .where(ImportItem.account_id == account_id)
            .group_by(ImportItem.status)
        )
        .tuples()
        .all()
    )

    # « Ce mois-ci » : items created this month that ended applied (both types).
    now = datetime.now(UTC)
    month_start = datetime(now.year, now.month, 1, tzinfo=UTC)
    applied_this_month = int(
        db.scalar(
            select(func.count()).where(
                EnrichmentItem.account_id == account_id,
                EnrichmentItem.status == "applied",
                EnrichmentItem.created_at >= month_start,
            )
        )
        or 0
    )
    imported_this_month = int(
        db.scalar(
            select(func.count()).where(
                ImportItem.account_id == account_id,
                ImportItem.status == "applied",
                ImportItem.created_at >= month_start,
            )
        )
        or 0
    )
    account = db.get(Account, account_id)
    settings = AccountSettings.model_validate(
        (account.settings_json if account else None) or {}
    )
    minutes_saved = (
        imported_this_month * settings.minutes_saved_per_import_product
        + applied_this_month * settings.minutes_saved_per_enriched_product
    )

    # Timing + resolution over settled items (Python-side date math: portable
    # across Postgres and the SQLite test database).
    settled = db.execute(
        select(
            EnrichmentItem.started_at,
            EnrichmentItem.finished_at,
            EnrichmentItem.source_method,
        ).where(
            EnrichmentItem.account_id == account_id,
            EnrichmentItem.status.in_(_SETTLED),
        )
    ).all()
    durations = [
        (finished - started).total_seconds()
        for started, finished, _ in settled
        if started is not None and finished is not None
    ]
    resolved_methods = [method for _, _, method in settled if method]

    return DashboardStats(
        applied_items=item_counts.get("applied", 0),
        ready_items=item_counts.get("ready_for_review", 0),
        running_jobs=job_counts.get("pending", 0) + job_counts.get("processing", 0),
        jobs_total=sum(job_counts.values()),
        items_total=sum(item_counts.values()),
        avg_item_seconds=(sum(durations) / len(durations)) if durations else None,
        auto_resolve_rate=(
            sum(1 for m in resolved_methods if m in _AUTO_METHODS)
            / len(resolved_methods)
        )
        if resolved_methods
        else None,
        imports_to_transfer=import_item_counts.get("ready_for_review", 0),
        imports_processing=job_counts_typed.get(("import", "pending"), 0)
        + job_counts_typed.get(("import", "processing"), 0),
        failed_items=item_counts.get("failed", 0) + import_item_counts.get("failed", 0),
        enrich_failed_items=item_counts.get("failed", 0),
        import_failed_items=import_item_counts.get("failed", 0),
        applied_this_month=applied_this_month,
        imported_this_month=imported_this_month,
        minutes_saved_this_month=minutes_saved,
    )


@router.get("/dashboard", response_model=DashboardStats)
def dashboard_stats(db: SessionDep, current_user: CurrentUserDep) -> DashboardStats:
    """Headline numbers for the dashboard KPI row."""
    account_id = resolve_account_id(db, current_user)
    return _dashboard_stats(db, account_id)
