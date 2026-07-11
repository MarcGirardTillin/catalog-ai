"""Admin console routes: cross-account monitoring and operator settings.

Everything here is CurrentAdminDep-only. This is the ONLY surface where raw
provider costs, the billing coefficient (margin) and per-account drill-downs
are exposed — client-facing routes serve white-label (redacted) views.
"""

from datetime import datetime
from decimal import Decimal

from fastapi import APIRouter
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.deps import CurrentAdminDep, SessionDep
from app.api.exceptions import AppException
from app.api.routes.usage import _build_by_job, _build_summary, _parse_month
from app.api.schemas.admin import (
    AdminAccountActivity,
    AdminAccountSummary,
    AdminActivityEntry,
    AdminOverview,
    AdminOverviewLine,
)
from app.api.schemas.settings import AccountSettings
from app.api.schemas.usage import UsageByJob, UsageSummary
from app.models import Account, EnrichmentItem, EnrichmentJob, ImportItem, User

router = APIRouter(prefix="/admin", tags=["admin"])

_ACTIVITY_LIMIT = 20


def _get_account(db: Session, account_id: int) -> Account:
    account = db.get(Account, account_id)
    if account is None:
        raise AppException(
            status_code=404, code="not_found", message="Account not found"
        )
    return account


@router.get("/accounts", response_model=list[AdminAccountSummary])
def list_accounts(
    db: SessionDep, _current_user: CurrentAdminDep
) -> list[AdminAccountSummary]:
    """Every account with its user count and latest activity."""
    accounts = db.scalars(select(Account).order_by(Account.id)).all()
    user_counts: dict[int, int] = {
        account_id: count
        for account_id, count in db.execute(
            select(User.account_id, func.count())
            .where(User.account_id.is_not(None))
            .group_by(User.account_id)
        )
        .tuples()
        .all()
        if account_id is not None  # narrowed by the WHERE; mypy can't see it
    }
    last_activity: dict[int, datetime] = dict(
        db.execute(
            select(
                EnrichmentJob.account_id, func.max(EnrichmentJob.created_at)
            ).group_by(EnrichmentJob.account_id)
        )
        .tuples()
        .all()
    )
    return [
        AdminAccountSummary(
            id=account.id,
            name=account.name,
            user_count=user_counts.get(account.id, 0),
            created_at=account.created_at,
            last_activity_at=last_activity.get(account.id),
        )
        for account in accounts
    ]


@router.get("/overview", response_model=AdminOverview)
def read_overview(
    db: SessionDep, _current_user: CurrentAdminDep, month: str | None = None
) -> AdminOverview:
    """Per-account monthly monitoring: cost vs billable (margin), volumes."""
    label, start, end = _parse_month(month)
    accounts = db.scalars(select(Account).order_by(Account.id)).all()
    lines: list[AdminOverviewLine] = []
    for account in accounts:
        summary = _build_summary(db, account.id, label, start, end)
        cost = Decimal(summary.totals.cost)
        billable = Decimal(summary.totals.billable)
        month_jobs = (
            select(EnrichmentJob.id, EnrichmentJob.job_type)
            .where(
                EnrichmentJob.account_id == account.id,
                EnrichmentJob.created_at >= start,
                EnrichmentJob.created_at < end,
            )
            .subquery()
        )
        counts_by_type: dict[str, int] = dict(
            db.execute(
                select(month_jobs.c.job_type, func.count()).group_by(
                    month_jobs.c.job_type
                )
            )
            .tuples()
            .all()
        )
        failed_enrich = db.scalar(
            select(func.count())
            .select_from(EnrichmentItem)
            .join(month_jobs, EnrichmentItem.job_id == month_jobs.c.id)
            .where(EnrichmentItem.status == "failed")
        )
        failed_import = db.scalar(
            select(func.count())
            .select_from(ImportItem)
            .join(month_jobs, ImportItem.job_id == month_jobs.c.id)
            .where(ImportItem.status == "failed")
        )
        lines.append(
            AdminOverviewLine(
                account_id=account.id,
                account_name=account.name,
                cost=str(cost),
                billable=str(billable),
                margin=str(billable - cost),
                coefficient=summary.coefficient,
                jobs_count=counts_by_type.get("enrichment", 0),
                imports_count=counts_by_type.get("import", 0),
                failed_items=int(failed_enrich or 0) + int(failed_import or 0),
            )
        )
    return AdminOverview(month=label, currency="EUR", lines=lines)


@router.get("/accounts/{account_id}/usage", response_model=UsageSummary)
def read_account_usage(
    account_id: int,
    db: SessionDep,
    _current_user: CurrentAdminDep,
    month: str | None = None,
) -> UsageSummary:
    """FULL (non-redacted) monthly summary of one account."""
    _get_account(db, account_id)
    label, start, end = _parse_month(month)
    return _build_summary(db, account_id, label, start, end)


@router.get("/accounts/{account_id}/usage/by-job", response_model=UsageByJob)
def read_account_usage_by_job(
    account_id: int,
    db: SessionDep,
    _current_user: CurrentAdminDep,
    month: str | None = None,
) -> UsageByJob:
    """FULL (non-redacted) per-job breakdown of one account."""
    _get_account(db, account_id)
    label, start, end = _parse_month(month)
    return _build_by_job(db, account_id, label, start, end)


@router.get("/accounts/{account_id}/activity", response_model=AdminAccountActivity)
def read_account_activity(
    account_id: int, db: SessionDep, _current_user: CurrentAdminDep
) -> AdminAccountActivity:
    """Latest jobs and imports of one account (monitoring feed)."""
    _get_account(db, account_id)
    jobs = db.scalars(
        select(EnrichmentJob)
        .where(EnrichmentJob.account_id == account_id)
        .order_by(EnrichmentJob.created_at.desc())
        .limit(_ACTIVITY_LIMIT)
    ).all()
    job_ids = [job.id for job in jobs]

    # SQLite/Postgres portable counts: grouped queries per item table.
    totals_enrich: dict[int, int] = dict(
        db.execute(
            select(EnrichmentItem.job_id, func.count())
            .where(EnrichmentItem.job_id.in_(job_ids))
            .group_by(EnrichmentItem.job_id)
        )
        .tuples()
        .all()
    )
    failed_enrich: dict[int, int] = dict(
        db.execute(
            select(EnrichmentItem.job_id, func.count())
            .where(
                EnrichmentItem.job_id.in_(job_ids),
                EnrichmentItem.status == "failed",
            )
            .group_by(EnrichmentItem.job_id)
        )
        .tuples()
        .all()
    )
    totals_import: dict[int, int] = dict(
        db.execute(
            select(ImportItem.job_id, func.count())
            .where(ImportItem.job_id.in_(job_ids))
            .group_by(ImportItem.job_id)
        )
        .tuples()
        .all()
    )
    failed_import: dict[int, int] = dict(
        db.execute(
            select(ImportItem.job_id, func.count())
            .where(ImportItem.job_id.in_(job_ids), ImportItem.status == "failed")
            .group_by(ImportItem.job_id)
        )
        .tuples()
        .all()
    )

    entries: list[AdminActivityEntry] = []
    for job in jobs:
        if job.job_type == "import":
            from app.imports.selection import stored_import_files

            names = [entry["file_name"] for entry in stored_import_files(job)]
            label = names[0] if names else f"Import #{job.id}"
            total = totals_import.get(job.id, 0)
            failed = failed_import.get(job.id, 0)
        else:
            label = f"Enrichissement #{job.id}"
            total = totals_enrich.get(job.id, 0)
            failed = failed_enrich.get(job.id, 0)
        entries.append(
            AdminActivityEntry(
                job_id=job.id,
                job_type=job.job_type,
                label=label,
                status=job.status,
                total_items=total,
                failed_items=failed,
                created_at=job.created_at,
            )
        )
    return AdminAccountActivity(account_id=account_id, entries=entries)


@router.get("/accounts/{account_id}/settings", response_model=AccountSettings)
def read_account_settings_admin(
    account_id: int, db: SessionDep, _current_user: CurrentAdminDep
) -> AccountSettings:
    """One account's settings, operator view (all fields)."""
    account = _get_account(db, account_id)
    return AccountSettings.model_validate(account.settings_json or {})


@router.put("/accounts/{account_id}/settings", response_model=AccountSettings)
def update_account_settings_admin(
    account_id: int,
    payload: AccountSettings,
    db: SessionDep,
    _current_user: CurrentAdminDep,
) -> AccountSettings:
    """Operator write of one account's settings (incl. admin-only fields:
    billing coefficient, dashboard time-saved minutes)."""
    account = _get_account(db, account_id)
    account.settings_json = payload.model_dump()
    db.commit()
    return payload
