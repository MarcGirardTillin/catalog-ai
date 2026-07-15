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
from app.api.routes.credits import build_credit_timeseries
from app.api.routes.usage import (
    _build_by_job,
    _build_summary,
    _build_timeseries,
    _parse_month,
    _price_lookup,
    _resolve_price,
)
from app.api.schemas.admin import (
    AdminAccountActivity,
    AdminAccountSummary,
    AdminActivityEntry,
    AdminOverview,
    AdminOverviewLine,
    AdminUsageMetric,
)
from app.api.schemas.credits import (
    AdminCredits,
    CreditEntryPublic,
    CreditGrantRequest,
    CreditTimeseries,
)
from app.api.schemas.settings import AccountSettings, OperatorSettings
from app.api.schemas.usage import UsageByJob, UsageSummary, UsageTimeseries
from app.api.services.accounts import (
    get_or_create_default_account,
    resolve_account_id,
)
from app.api.services.credits import balance as credit_balance
from app.models import (
    Account,
    CreditEntry,
    EnrichmentItem,
    EnrichmentJob,
    ImportItem,
    UsageEvent,
    User,
)

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


@router.get("/usage-metrics", response_model=list[AdminUsageMetric])
def list_usage_metrics(
    db: SessionDep, current_user: CurrentAdminDep
) -> list[AdminUsageMetric]:
    """Every (provider, model, metric) combo the app has actually recorded.

    Source of truth for the pricing form's metric picker: prices created from
    this list always match real events (free-text metrics caused silent
    "unpriced" gaps). `priced` resolves against the caller's grid with the
    same exact-then-model-null fallback as the billing code.
    """
    account_id = resolve_account_id(db, current_user)
    lookup = _price_lookup(db, account_id)
    rows = db.execute(
        select(
            UsageEvent.provider,
            UsageEvent.model,
            UsageEvent.metric,
            func.sum(UsageEvent.quantity),
        ).group_by(UsageEvent.provider, UsageEvent.model, UsageEvent.metric)
    ).all()
    metrics = [
        AdminUsageMetric(
            provider=provider,
            model=model,
            metric=metric,
            quantity=int(quantity or 0),
            priced=_resolve_price(lookup, provider, model, metric) is not None,
        )
        for provider, model, metric, quantity in rows
    ]
    metrics.sort(key=lambda m: (m.priced, m.provider, m.model or "", m.metric))
    return metrics


# Groupements de série temporelle exposés à l'admin. "service" agrège les
# providers par libellé neutre (Génération de texte / Traitement d'image /
# Recherche produit) — même mapping que la vue client expurgée.
_TIMESERIES_GROUPS = ("none", "service", "model", "provider")


def _check_group_by(group_by: str) -> None:
    if group_by not in _TIMESERIES_GROUPS:
        raise AppException(
            status_code=422,
            code="invalid_group_by",
            message="group_by must be one of: " + ", ".join(_TIMESERIES_GROUPS),
        )


@router.get("/timeseries", response_model=UsageTimeseries)
def read_admin_timeseries(
    db: SessionDep,
    _current_user: CurrentAdminDep,
    month: str | None = None,
    group_by: str = "none",
) -> UsageTimeseries:
    """Daily billable series summed over ALL accounts (operator monitoring).

    Amounts are billable (cost × each account's own coefficient), so the
    total curve matches what the overview bills across the customer base.
    """
    _check_group_by(group_by)
    label, start, end = _parse_month(month)
    account_ids = list(db.scalars(select(Account.id).order_by(Account.id)).all())
    return _build_timeseries(db, account_ids, label, start, end, group_by)


@router.get("/accounts/{account_id}/timeseries", response_model=UsageTimeseries)
def read_account_timeseries(
    account_id: int,
    db: SessionDep,
    _current_user: CurrentAdminDep,
    month: str | None = None,
    group_by: str = "none",
) -> UsageTimeseries:
    """Daily billable series of ONE account (full operator view)."""
    _check_group_by(group_by)
    _get_account(db, account_id)
    label, start, end = _parse_month(month)
    return _build_timeseries(db, [account_id], label, start, end, group_by)


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


@router.get("/settings", response_model=OperatorSettings)
def read_operator_settings(
    db: SessionDep, _current_user: CurrentAdminDep
) -> OperatorSettings:
    """The GLOBAL operator settings (credit grid, packs, quota, minutes).

    Read from the default account — PUT keeps every account in sync, so any
    account is representative.
    """
    account = get_or_create_default_account(db)
    return OperatorSettings.model_validate(account.settings_json or {})


@router.put("/settings", response_model=OperatorSettings)
def update_operator_settings(
    payload: OperatorSettings,
    db: SessionDep,
    _current_user: CurrentAdminDep,
) -> OperatorSettings:
    """Write the operator settings to EVERY account (global policy).

    Only the operator-owned keys are touched — each account keeps its own
    client-facing settings (templates, imaging defaults…).
    """
    get_or_create_default_account(db)  # ensure at least one account exists
    updates = payload.model_dump()
    for account in db.scalars(select(Account)).all():
        account.settings_json = {**(account.settings_json or {}), **updates}
    db.commit()
    return payload


@router.get(
    "/accounts/{account_id}/credits/timeseries", response_model=CreditTimeseries
)
def read_account_credit_timeseries(
    account_id: int,
    db: SessionDep,
    _current_user: CurrentAdminDep,
    month: str | None = None,
) -> CreditTimeseries:
    """Daily credits consumed by ONE account (operator chart view)."""
    _get_account(db, account_id)
    return build_credit_timeseries(db, account_id, month)


@router.get("/accounts/{account_id}/credits", response_model=AdminCredits)
def read_account_credits(
    account_id: int, db: SessionDep, _current_user: CurrentAdminDep
) -> AdminCredits:
    """One account's credit balance + last ledger entries (all kinds)."""
    _get_account(db, account_id)
    entries = db.scalars(
        select(CreditEntry)
        .where(CreditEntry.account_id == account_id)
        .order_by(CreditEntry.id.desc())
        .limit(50)
    ).all()
    return AdminCredits(
        balance=credit_balance(db, account_id),
        entries=[
            CreditEntryPublic.model_validate(entry, from_attributes=True)
            for entry in entries
        ],
    )


@router.post("/accounts/{account_id}/credits/grant", response_model=AdminCredits)
def grant_account_credits(
    account_id: int,
    payload: CreditGrantRequest,
    db: SessionDep,
    current_user: CurrentAdminDep,
) -> AdminCredits:
    """Record a manual ledger entry (grant / pack purchase / adjustment).

    `credits` is signed: a negative adjustment removes credits. Pack purchases
    are bookkept here by the operator — no online payment in this scope.
    """
    _get_account(db, account_id)
    if payload.credits == 0:
        raise AppException(
            status_code=422, code="empty_grant", message="credits must be non-zero"
        )
    db.add(
        CreditEntry(
            account_id=account_id,
            kind=payload.kind,
            credits=payload.credits,
            label=payload.label,
            price_eur=payload.price_eur,
            created_by=current_user.id,
        )
    )
    db.commit()
    return read_account_credits(account_id, db, current_user)


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
