"""Client-facing credit routes: balance overview and daily consumption.

The admin ledger (grant, per-account view) lives under /admin — see
`app.api.routes.admin`. Everything here is scoped to the caller's account and
carries no euro amounts except the displayed pack prices (white-label rule:
costs and margins never reach a client payload).
"""

from collections import defaultdict
from datetime import UTC, timedelta

from fastapi import APIRouter
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import CurrentUserDep, SessionDep
from app.api.routes.usage import _parse_month
from app.api.schemas.credits import (
    CreditEntryPublic,
    CreditMonth,
    CreditOverview,
    CreditTimeseries,
    CreditTimeseriesPoint,
    CreditTimeseriesSeries,
)
from app.api.services.accounts import resolve_account_id
from app.api.services.credits import account_credit_settings, balance
from app.models import CreditEntry

router = APIRouter(prefix="/credits", tags=["credits"])

# Neutral client-facing labels of the billable actions (fixed display order).
ACTION_LABELS = {
    "import_product": "Produits importés",
    "enrich_item": "Fiches enrichies",
    "image_process": "Images traitées",
    "image_generate": "Visuels générés",
}


@router.get("", response_model=CreditOverview)
def read_credits(
    db: SessionDep, current_user: CurrentUserDep, month: str | None = None
) -> CreditOverview:
    """Balance, packs and the month's movements for the caller's account."""
    account_id = resolve_account_id(db, current_user)
    current_balance = balance(db, account_id)  # lazy subscription grant first
    settings = account_credit_settings(db, account_id)
    label, start, end = _parse_month(month)

    rows = db.scalars(
        select(CreditEntry)
        .where(
            CreditEntry.account_id == account_id,
            CreditEntry.created_at >= start,
            CreditEntry.created_at < end,
        )
        .order_by(CreditEntry.created_at.desc())
    ).all()
    by_action: dict[str, int] = {}
    consumed_total = 0
    movements = []
    for entry in rows:
        if entry.kind == "consumption":
            consumed_total += -entry.credits
            if entry.action:
                by_action[entry.action] = by_action.get(entry.action, 0) + (
                    entry.quantity or 0
                )
        else:
            movements.append(entry)
    return CreditOverview(
        balance=current_balance,
        low_credit_threshold=settings.low_credit_threshold,
        monthly_free_credits=settings.monthly_free_credits,
        packs=settings.credit_packs,
        month=CreditMonth(
            month=label, consumed_total=consumed_total, by_action=by_action
        ),
        entries=[
            CreditEntryPublic.model_validate(entry, from_attributes=True)
            for entry in movements[:50]
        ],
    )


def build_credit_timeseries(
    db: Session, account_id: int, month: str | None
) -> CreditTimeseries:
    """Daily credits consumed, one series per action (full month, 0-filled).

    Shared by the client route below and the admin per-account view.
    """
    label, start, end = _parse_month(month)
    rows = db.execute(
        select(CreditEntry.created_at, CreditEntry.action, CreditEntry.credits).where(
            CreditEntry.account_id == account_id,
            CreditEntry.kind == "consumption",
            CreditEntry.created_at >= start,
            CreditEntry.created_at < end,
        )
    ).all()
    consumed: dict[tuple[str, str], int] = defaultdict(int)
    seen_actions: set[str] = set()
    for created_at, action, credits in rows:
        day = (
            created_at.astimezone(UTC).date()
            if created_at.tzinfo is not None
            else created_at.date()
        )
        key = ACTION_LABELS.get(action or "", "Autre")
        seen_actions.add(key)
        consumed[(key, day.isoformat())] += -int(credits or 0)

    days = []
    cursor = start.date()
    while cursor < end.date():
        days.append(cursor.isoformat())
        cursor += timedelta(days=1)

    ordered = [label_ for label_ in ACTION_LABELS.values() if label_ in seen_actions]
    if "Autre" in seen_actions:
        ordered.append("Autre")
    series = [
        CreditTimeseriesSeries(
            key=key,
            points=[
                CreditTimeseriesPoint(date=day, credits=consumed.get((key, day), 0))
                for day in days
            ],
        )
        for key in ordered
    ]
    return CreditTimeseries(month=label, series=series)


@router.get("/timeseries", response_model=CreditTimeseries)
def read_credit_timeseries(
    db: SessionDep, current_user: CurrentUserDep, month: str | None = None
) -> CreditTimeseries:
    """Daily credits consumed by the caller's account."""
    account_id = resolve_account_id(db, current_user)
    return build_credit_timeseries(db, account_id, month)
