"""Prepaid credit logic: grid, balance, lazy subscription grant, consumption.

`consume` deliberately does NOT commit — the caller owns the transaction, so
the debit lands atomically with the work it pays for (same rule as
`record_usage`). The monthly subscription allocation is granted lazily the
first time the balance is read in a new month (same philosophy as the billing
snapshot freeze: no scheduler).
"""

from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.exceptions import AppException
from app.api.schemas.settings import AccountSettings
from app.models import Account, CreditEntry


def account_credit_settings(db: Session, account_id: int) -> AccountSettings:
    account = db.get(Account, account_id)
    return AccountSettings.model_validate(
        (account.settings_json if account else None) or {}
    )


def credit_grid(db: Session, account_id: int) -> dict[str, int]:
    """Per-action credit price for the account (settings defaults filled in)."""
    settings = account_credit_settings(db, account_id)
    return {
        "import_product": settings.credit_cost_import_product,
        "enrich_item": settings.credit_cost_enrich_item,
        "image_process": settings.credit_cost_image_process,
        "image_generate": settings.credit_cost_image_generate,
    }


def _current_period() -> str:
    now = datetime.now(UTC)
    return f"{now.year:04d}-{now.month:02d}"


def ensure_subscription_grant(db: Session, account_id: int) -> None:
    """Grant the month's free credits once (lazy, idempotent per period).

    Commits on insert: the allocation must survive even if the caller's
    transaction rolls back (it is a fact of the subscription, not of the
    request that happened to trigger it).
    """
    settings = account_credit_settings(db, account_id)
    if settings.monthly_free_credits <= 0:
        return
    period = _current_period()
    exists = db.scalar(
        select(CreditEntry.id).where(
            CreditEntry.account_id == account_id,
            CreditEntry.kind == "subscription",
            CreditEntry.period == period,
        )
    )
    if exists is not None:
        return
    db.add(
        CreditEntry(
            account_id=account_id,
            kind="subscription",
            credits=settings.monthly_free_credits,
            period=period,
            label="Crédits mensuels inclus",
        )
    )
    db.commit()


def balance(db: Session, account_id: int) -> int:
    """Current balance (after the lazy subscription grant)."""
    ensure_subscription_grant(db, account_id)
    return int(
        db.scalar(
            select(func.coalesce(func.sum(CreditEntry.credits), 0)).where(
                CreditEntry.account_id == account_id
            )
        )
        or 0
    )


def consume(
    db: Session,
    *,
    account_id: int,
    action: str,
    quantity: int,
    job_id: int | None = None,
    item_id: int | None = None,
    asset_id: int | None = None,
) -> CreditEntry | None:
    """Stage one consumption debit on the session (no commit — caller commits).

    Free actions (unit price 0 in the grid) and empty quantities write nothing:
    the ledger only carries movements.
    """
    if quantity <= 0:
        return None
    unit = credit_grid(db, account_id).get(action, 0)
    if unit <= 0:
        return None
    entry = CreditEntry(
        account_id=account_id,
        kind="consumption",
        credits=-(quantity * unit),
        action=action,
        quantity=quantity,
        unit_credits=unit,
        job_id=job_id,
        item_id=item_id,
        asset_id=asset_id,
    )
    db.add(entry)
    return entry


def require_credits(db: Session, account_id: int, needed: int) -> None:
    """Refuse a launch when the balance cannot cover it (402, nothing written)."""
    if needed <= 0:
        return
    current = balance(db, account_id)
    if current < needed:
        raise AppException(
            status_code=402,
            code="insufficient_credits",
            message=f"Crédits insuffisants (solde {current}, requis {needed})",
        )
