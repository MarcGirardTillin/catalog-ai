"""Supplier cost grid resolution (operator margin view only).

`usage_price` holds the REAL provider costs. Rows with `account_id IS NULL`
form the platform-wide COMMON grid; rows with an `account_id` are that
account's exceptions (negotiated discounts…). For an event of an account the
unit price resolves, first hit wins:

1. (account, provider, exact model, metric)
2. (account, provider, model NULL, metric)
3. (common,  provider, exact model, metric)
4. (common,  provider, model NULL, metric)
5. no price

This module is the ONLY place that resolves a price — summary, by-job,
export, timeseries, admin overview, metric picker and the monthly freeze all
go through `PriceGrid.resolve`.
"""

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import UsagePrice

PriceKey = tuple[str, str | None, str]  # (provider, model|None, metric)

SCOPE_ACCOUNT = "account"
SCOPE_COMMON = "common"


def _pick(table: dict[PriceKey, Decimal], key: PriceKey) -> Decimal | None:
    exact = table.get(key)
    if exact is not None:
        return exact
    provider, _model, metric = key
    return table.get((provider, None, metric))


@dataclass(frozen=True)
class PriceGrid:
    """Resolved view of the grid for ONE account (exceptions + common)."""

    account: dict[PriceKey, Decimal] = field(default_factory=dict)
    common: dict[PriceKey, Decimal] = field(default_factory=dict)

    def resolve(self, provider: str, model: str | None, metric: str) -> Decimal | None:
        key = (provider, model, metric)
        found = _pick(self.account, key)
        if found is not None:
            return found
        return _pick(self.common, key)


def _rows_to_table(rows: Any) -> dict[PriceKey, Decimal]:
    # Ordered by id: should duplicates exist, the most recent row wins
    # deterministically (the API refuses to create new duplicates).
    return {(p.provider, p.model, p.metric): p.unit_price for p in rows}


def common_prices(db: Session) -> list[UsagePrice]:
    return list(
        db.scalars(
            select(UsagePrice)
            .where(UsagePrice.account_id.is_(None))
            .order_by(UsagePrice.id)
        ).all()
    )


def account_prices(db: Session, account_id: int) -> list[UsagePrice]:
    return list(
        db.scalars(
            select(UsagePrice)
            .where(UsagePrice.account_id == account_id)
            .order_by(UsagePrice.id)
        ).all()
    )


def load_common_grid(db: Session) -> PriceGrid:
    """The common grid alone (no account exceptions)."""
    return PriceGrid(account={}, common=_rows_to_table(common_prices(db)))


def load_price_grid(db: Session, account_id: int) -> PriceGrid:
    """The live grid of an account: its exceptions over the common grid."""
    return PriceGrid(
        account=_rows_to_table(account_prices(db, account_id)),
        common=_rows_to_table(common_prices(db)),
    )


def serialize_grid(grid: PriceGrid) -> list[dict[str, Any]]:
    """Grid serialized for a billing snapshot, scope kept so the cascade
    replays identically on a frozen month."""
    rows: list[dict[str, Any]] = []
    for scope, table in ((SCOPE_ACCOUNT, grid.account), (SCOPE_COMMON, grid.common)):
        for (provider, model, metric), unit_price in table.items():
            rows.append(
                {
                    "scope": scope,
                    "provider": provider,
                    "model": model,
                    "metric": metric,
                    "unit_price": str(unit_price),
                }
            )
    return rows


def grid_from_snapshot(prices_json: list[dict[str, Any]]) -> PriceGrid:
    """Rebuild a grid from a snapshot. Snapshots taken before the common grid
    carry no `scope`: they were the account's own rows → account scope."""
    account: dict[PriceKey, Decimal] = {}
    common: dict[PriceKey, Decimal] = {}
    for row in prices_json:
        table = common if row.get("scope") == SCOPE_COMMON else account
        table[(row["provider"], row["model"], row["metric"])] = Decimal(
            str(row["unit_price"])
        )
    return PriceGrid(account=account, common=common)
