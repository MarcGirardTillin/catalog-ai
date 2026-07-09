"""Usage reporting routes: price CRUD, monthly summary, per-job breakdown, CSV.

Frozen plan principle: cost is NEVER stored on usage events — it is computed
at read time from `usage_price`, so the account can be repriced at any moment.
Price resolution for an event: exact (provider, model, metric) first, then the
provider-wide fallback (provider, model IS NULL, metric), else no price.
"""

import csv
import io
import re
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal

from fastapi import APIRouter, Response
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.deps import CurrentUserDep, SessionDep
from app.api.exceptions import AppException
from app.api.schemas.settings import AccountSettings
from app.api.schemas.usage import (
    UsageByJob,
    UsageJobLine,
    UsageJobMetric,
    UsagePriceCreate,
    UsagePricePublic,
    UsagePriceUpdate,
    UsageSummary,
    UsageSummaryLine,
    UsageTotals,
)
from app.api.services.accounts import resolve_account_id
from app.models import Account, EnrichmentJob, UsageEvent, UsagePrice

router = APIRouter(prefix="/usage", tags=["usage"])

# Display precision for money values (unit prices keep their full scale).
_CENTS = Decimal("0.0001")


def _parse_month(month: str | None) -> tuple[str, datetime, datetime]:
    """Validate ?month=YYYY-MM (default: current UTC month) → (label, start, end)."""
    if month is None:
        now = datetime.now(UTC)
        year, mon = now.year, now.month
    else:
        matched = re.fullmatch(r"(\d{4})-(\d{2})", month)
        if matched is None or not 1 <= int(matched.group(2)) <= 12:
            raise AppException(
                status_code=422,
                code="invalid_month",
                message="Invalid month; expected YYYY-MM",
            )
        year, mon = int(matched.group(1)), int(matched.group(2))
    start = datetime(year, mon, 1, tzinfo=UTC)
    end = (
        datetime(year + 1, 1, 1, tzinfo=UTC)
        if mon == 12
        else datetime(year, mon + 1, 1, tzinfo=UTC)
    )
    return f"{year:04d}-{mon:02d}", start, end


def _billing_coefficient(db: Session, account_id: int) -> Decimal:
    account = db.get(Account, account_id)
    settings = AccountSettings.model_validate(
        (account.settings_json if account else None) or {}
    )
    return Decimal(str(settings.billing_coefficient))


def _price_lookup(
    db: Session, account_id: int
) -> dict[tuple[str, str | None, str], Decimal]:
    prices = db.scalars(
        select(UsagePrice).where(UsagePrice.account_id == account_id)
    ).all()
    return {(p.provider, p.model, p.metric): p.unit_price for p in prices}


def _resolve_price(
    lookup: dict[tuple[str, str | None, str], Decimal],
    provider: str,
    model: str | None,
    metric: str,
) -> Decimal | None:
    """Exact (provider, model, metric) first, then the model-null fallback."""
    exact = lookup.get((provider, model, metric))
    if exact is not None:
        return exact
    return lookup.get((provider, None, metric))


def _month_groups(
    db: Session, account_id: int, start: datetime, end: datetime
) -> list[tuple[str, str | None, str, int]]:
    """sum(quantity) per (provider, model, metric) for the account and month."""
    rows = db.execute(
        select(
            UsageEvent.provider,
            UsageEvent.model,
            UsageEvent.metric,
            func.sum(UsageEvent.quantity),
        )
        .where(
            UsageEvent.account_id == account_id,
            UsageEvent.created_at >= start,
            UsageEvent.created_at < end,
        )
        .group_by(UsageEvent.provider, UsageEvent.model, UsageEvent.metric)
    ).all()
    groups = [
        (provider, model, metric, int(quantity or 0))
        for provider, model, metric, quantity in rows
    ]
    groups.sort(key=lambda g: (g[0], g[1] or "", g[2]))
    return groups


def _to_public(price: UsagePrice) -> UsagePricePublic:
    return UsagePricePublic(
        id=price.id,
        provider=price.provider,
        model=price.model,
        metric=price.metric,
        unit_price=str(price.unit_price),
        currency=price.currency,
    )


def _get_price(db: Session, *, account_id: int, price_id: int) -> UsagePrice:
    price = db.get(UsagePrice, price_id)
    if price is None or price.account_id != account_id:
        raise AppException(
            status_code=404, code="not_found", message="Usage price not found"
        )
    return price


@router.get("/prices", response_model=list[UsagePricePublic])
def list_usage_prices(
    db: SessionDep, current_user: CurrentUserDep
) -> list[UsagePricePublic]:
    account_id = resolve_account_id(db, current_user)
    prices = db.scalars(
        select(UsagePrice).where(UsagePrice.account_id == account_id)
    ).all()
    ordered = sorted(prices, key=lambda p: (p.provider, p.model or "", p.metric))
    return [_to_public(price) for price in ordered]


@router.post("/prices", response_model=UsagePricePublic, status_code=201)
def create_usage_price(
    payload: UsagePriceCreate, db: SessionDep, current_user: CurrentUserDep
) -> UsagePricePublic:
    account_id = resolve_account_id(db, current_user)
    price = UsagePrice(
        account_id=account_id,
        provider=payload.provider,
        model=payload.model,
        metric=payload.metric,
        unit_price=payload.unit_price,
        currency=payload.currency,
    )
    db.add(price)
    db.commit()
    db.refresh(price)
    return _to_public(price)


@router.patch("/prices/{price_id}", response_model=UsagePricePublic)
def update_usage_price(
    price_id: int,
    payload: UsagePriceUpdate,
    db: SessionDep,
    current_user: CurrentUserDep,
) -> UsagePricePublic:
    account_id = resolve_account_id(db, current_user)
    price = _get_price(db, account_id=account_id, price_id=price_id)
    updates = payload.model_dump(exclude_unset=True)
    for name, value in updates.items():
        setattr(price, name, value)
    db.commit()
    db.refresh(price)
    return _to_public(price)


@router.delete("/prices/{price_id}", status_code=204)
def delete_usage_price(
    price_id: int, db: SessionDep, current_user: CurrentUserDep
) -> None:
    account_id = resolve_account_id(db, current_user)
    price = _get_price(db, account_id=account_id, price_id=price_id)
    db.delete(price)
    db.commit()


def _build_summary(
    db: Session, account_id: int, month: str, start: datetime, end: datetime
) -> UsageSummary:
    coefficient = _billing_coefficient(db, account_id)
    lookup = _price_lookup(db, account_id)
    lines: list[UsageSummaryLine] = []
    total_cost = Decimal(0)
    total_billable = Decimal(0)
    unpriced_count = 0
    for provider, model, metric, quantity in _month_groups(db, account_id, start, end):
        unit_price = _resolve_price(lookup, provider, model, metric)
        if unit_price is None:
            unpriced_count += 1
            lines.append(
                UsageSummaryLine(
                    provider=provider,
                    model=model,
                    metric=metric,
                    quantity=quantity,
                    unit_price=None,
                    cost=None,
                    billable=None,
                )
            )
            continue
        cost = (Decimal(quantity) * unit_price).quantize(_CENTS)
        billable = (cost * coefficient).quantize(_CENTS)
        total_cost += cost
        total_billable += billable
        lines.append(
            UsageSummaryLine(
                provider=provider,
                model=model,
                metric=metric,
                quantity=quantity,
                unit_price=str(unit_price),
                cost=str(cost),
                billable=str(billable),
            )
        )
    return UsageSummary(
        month=month,
        currency="EUR",
        coefficient=float(coefficient),
        lines=lines,
        totals=UsageTotals(
            cost=str(total_cost.quantize(_CENTS)),
            billable=str(total_billable.quantize(_CENTS)),
        ),
        unpriced_count=unpriced_count,
    )


@router.get("/summary", response_model=UsageSummary)
def read_usage_summary(
    db: SessionDep, current_user: CurrentUserDep, month: str | None = None
) -> UsageSummary:
    """Monthly consumption per (provider, model, metric), priced at read time."""
    account_id = resolve_account_id(db, current_user)
    label, start, end = _parse_month(month)
    return _build_summary(db, account_id, label, start, end)


@dataclass
class _JobBucket:
    """Running aggregates for one job while folding the grouped event rows."""

    input_tokens: int = 0
    output_tokens: int = 0
    other: dict[tuple[str, str], int] = field(default_factory=dict)
    cost: Decimal = Decimal(0)
    priced: bool = False  # at least one metric had a price


@router.get("/by-job", response_model=UsageByJob)
def read_usage_by_job(
    db: SessionDep, current_user: CurrentUserDep, month: str | None = None
) -> UsageByJob:
    """Monthly consumption grouped by job (null job_id = "Hors job")."""
    account_id = resolve_account_id(db, current_user)
    label, start, end = _parse_month(month)
    coefficient = _billing_coefficient(db, account_id)
    lookup = _price_lookup(db, account_id)

    rows = db.execute(
        select(
            UsageEvent.job_id,
            UsageEvent.provider,
            UsageEvent.model,
            UsageEvent.metric,
            func.sum(UsageEvent.quantity),
        )
        .where(
            UsageEvent.account_id == account_id,
            UsageEvent.created_at >= start,
            UsageEvent.created_at < end,
        )
        .group_by(
            UsageEvent.job_id, UsageEvent.provider, UsageEvent.model, UsageEvent.metric
        )
    ).all()

    job_ids = {row[0] for row in rows if row[0] is not None}
    jobs_by_id: dict[int, EnrichmentJob] = {
        job.id: job
        for job in db.scalars(
            select(EnrichmentJob).where(EnrichmentJob.id.in_(job_ids))
        ).all()
    }

    # Per job: token counters, non-token metrics, and the priced-cost sum.
    grouped: dict[int | None, _JobBucket] = {}
    for job_id, provider, model, metric, quantity_raw in rows:
        quantity = int(quantity_raw or 0)
        bucket = grouped.setdefault(job_id, _JobBucket())
        if metric == "input_tokens":
            bucket.input_tokens += quantity
        elif metric == "output_tokens":
            bucket.output_tokens += quantity
        else:
            key = (provider, metric)
            bucket.other[key] = bucket.other.get(key, 0) + quantity
        unit_price = _resolve_price(lookup, provider, model, metric)
        if unit_price is not None:
            bucket.cost += Decimal(quantity) * unit_price
            bucket.priced = True

    lines: list[UsageJobLine] = []
    for job_id, bucket in grouped.items():
        job = jobs_by_id.get(job_id) if job_id is not None else None
        if job_id is None:
            label_text = "Hors job"
        elif job is not None and job.job_type == "import":
            file_name = (job.selection_json or {}).get("file_name")
            label_text = str(file_name) if file_name else f"Job #{job_id}"
        else:
            label_text = f"Job #{job_id}"
        cost = bucket.cost.quantize(_CENTS) if bucket.priced else None
        billable = (cost * coefficient).quantize(_CENTS) if cost is not None else None
        lines.append(
            UsageJobLine(
                job_id=job_id,
                job_type=job.job_type if job is not None else None,
                label=label_text,
                created_at=job.created_at if job is not None else None,
                input_tokens=bucket.input_tokens,
                output_tokens=bucket.output_tokens,
                other_metrics=[
                    UsageJobMetric(provider=provider, metric=metric, quantity=quantity)
                    for (provider, metric), quantity in sorted(bucket.other.items())
                ],
                cost=str(cost) if cost is not None else None,
                billable=str(billable) if billable is not None else None,
            )
        )

    # Cost desc (unpriced last), then job_id desc ("Hors job" last).
    lines.sort(
        key=lambda line: (
            line.cost is not None,
            Decimal(line.cost) if line.cost is not None else Decimal(0),
            line.job_id if line.job_id is not None else -1,
        ),
        reverse=True,
    )
    return UsageByJob(month=label, jobs=lines)


@router.get("/export")
def export_usage_csv(
    db: SessionDep, current_user: CurrentUserDep, month: str | None = None
) -> Response:
    """The monthly summary as a CSV attachment (comma separated, with header)."""
    account_id = resolve_account_id(db, current_user)
    label, start, end = _parse_month(month)
    summary = _build_summary(db, account_id, label, start, end)

    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\r\n")
    writer.writerow(
        [
            "month",
            "provider",
            "model",
            "metric",
            "quantity",
            "unit_price",
            "cost",
            "coefficient",
            "billable",
        ]
    )
    for line in summary.lines:
        writer.writerow(
            [
                summary.month,
                line.provider,
                line.model or "",
                line.metric,
                line.quantity,
                line.unit_price or "",
                line.cost or "",
                summary.coefficient,
                line.billable or "",
            ]
        )
    writer.writerow(
        [
            summary.month,
            "TOTAL",
            "",
            "",
            "",
            "",
            summary.totals.cost,
            summary.coefficient,
            summary.totals.billable,
        ]
    )
    return Response(
        content=buffer.getvalue(),
        media_type="text/csv",
        headers={
            "Content-Disposition": f'attachment; filename="consommation_{label}.csv"'
        },
    )
