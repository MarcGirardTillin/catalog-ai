"""Pure-Python planning of migration 0027 (common supplier cost grid).

The invariant under test: after the merge, every account resolves EXACTLY the
same unit price as before for every (provider, model, metric) it had a price
for — the cascade account exact → account NULL → common exact → common NULL.
"""

import importlib.util
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

_MIGRATION = (
    Path(__file__).resolve().parents[1]
    / "app"
    / "alembic"
    / "versions"
    / "0027_common_usage_price.py"
)


@pytest.fixture(scope="module")
def mig() -> ModuleType:
    spec = importlib.util.spec_from_file_location("mig_0027", _MIGRATION)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _row(
    mig: ModuleType,
    id: int,
    account_id: int | None,
    model: str | None,
    metric: str,
    price: str,
    *,
    provider: str = "claude",
    currency: str = "EUR",
    updated_at: datetime | None = None,
) -> Any:
    return mig.PriceRow(
        id=id,
        account_id=account_id,
        provider=provider,
        model=model,
        metric=metric,
        unit_price=Decimal(price),
        currency=currency,
        updated_at=updated_at,
    )


def _resolve(
    rows: list[Any], account_id: int, key: tuple[str, str | None, str]
) -> Decimal | None:
    """Reference cascade over a flat row list (account first, then common)."""
    provider, model, metric = key
    for scope in (account_id, None):
        table = {r.key: r.unit_price for r in rows if r.account_id == scope}
        for probe in ((provider, model, metric), (provider, None, metric)):
            if probe in table:
                return Decimal(table[probe])
    return None


def _apply(mig: ModuleType, rows: list[Any]) -> list[Any]:
    common, delete_ids = mig.plan_common_grid(rows)
    kept = [r for r in rows if r.id not in delete_ids]
    next_id = max(r.id for r in rows) + 1
    for i, c in enumerate(common):
        kept.append(
            _row(
                mig,
                next_id + i,
                None,
                c.model,
                c.metric,
                str(c.unit_price),
                provider=c.provider,
                currency=c.currency,
            )
        )
    return kept


def _assert_unchanged(rows: list[Any], after: list[Any]) -> None:
    keys = {r.key for r in rows} | {(r.provider, None, r.metric) for r in rows}
    keys |= {(r.provider, "unknown-model", r.metric) for r in rows}
    for account_id in {r.account_id for r in rows}:
        for key in keys:
            before = _resolve(rows, account_id, key)
            if before is None:
                continue
            assert _resolve(after, account_id, key) == before, (account_id, key)


def test_identical_copies_collapse_into_one_common_row(mig: ModuleType) -> None:
    rows = []
    next_id = 1
    for account_id in (1, 3, 4):
        for metric, price in (
            ("input_tokens", "0.000003"),
            ("output_tokens", "0.000015"),
        ):
            rows.append(
                _row(mig, next_id, account_id, "claude-sonnet-5", metric, price)
            )
            next_id += 1
    common, delete_ids = mig.plan_common_grid(rows)
    assert {(c.model, c.metric, c.unit_price) for c in common} == {
        ("claude-sonnet-5", "input_tokens", Decimal("0.000003")),
        ("claude-sonnet-5", "output_tokens", Decimal("0.000015")),
    }
    assert all(c.account_id is None for c in common)
    assert delete_ids == {r.id for r in rows}  # no exception left
    _assert_unchanged(rows, _apply(mig, rows))


def test_majority_price_wins_and_divergent_rows_stay_exceptions(
    mig: ModuleType,
) -> None:
    rows = [
        _row(mig, 1, 1, None, "edit", "0.075", provider="fashn"),
        _row(mig, 2, 2, None, "edit", "0.075", provider="fashn"),
        _row(mig, 3, 3, None, "edit", "0.05", provider="fashn"),  # negotiated
    ]
    common, delete_ids = mig.plan_common_grid(rows)
    assert [(c.unit_price) for c in common] == [Decimal("0.075")]
    assert delete_ids == {1, 2}
    _assert_unchanged(rows, _apply(mig, rows))


def test_tie_breaks_on_most_recent_updated_at(mig: ModuleType) -> None:
    old = datetime(2026, 7, 1, tzinfo=UTC)
    new = datetime(2026, 9, 1, tzinfo=UTC)
    rows = [
        _row(mig, 1, 1, None, "images", "0.02", provider="photoroom", updated_at=new),
        _row(mig, 2, 2, None, "images", "0.03", provider="photoroom", updated_at=old),
    ]
    common, delete_ids = mig.plan_common_grid(rows)
    assert common[0].unit_price == Decimal("0.02")
    assert delete_ids == {1}
    _assert_unchanged(rows, _apply(mig, rows))


def test_currency_difference_is_kept_as_exception(mig: ModuleType) -> None:
    rows = [
        _row(mig, 1, 1, None, "images", "0.02", provider="photoroom"),
        _row(mig, 2, 2, None, "images", "0.02", provider="photoroom"),
        _row(mig, 3, 3, None, "images", "0.02", provider="photoroom", currency="USD"),
    ]
    _common, delete_ids = mig.plan_common_grid(rows)
    assert delete_ids == {1, 2}


def test_cascade_preserved_when_null_exception_shadows_common_exact(
    mig: ModuleType,
) -> None:
    """Account 3 prices every claude model with its own NULL row and has an
    exact row equal to the common one: deleting that exact row would let the
    NULL exception win → the exact row must be kept."""
    rows = [
        _row(mig, 1, 1, "claude-sonnet-5", "input_tokens", "0.000003"),
        _row(mig, 2, 2, "claude-sonnet-5", "input_tokens", "0.000003"),
        _row(mig, 3, 3, "claude-sonnet-5", "input_tokens", "0.000003"),
        _row(mig, 4, 3, None, "input_tokens", "0.000001"),
        # Account 4 relies on its NULL row for opus; common gets an opus row
        # from the majority of accounts 1/2 — 4's NULL must stay authoritative.
        _row(mig, 5, 1, None, "input_tokens", "0.000005"),
        _row(mig, 6, 2, None, "input_tokens", "0.000005"),
        _row(mig, 7, 4, None, "input_tokens", "0.000005"),
        _row(mig, 8, 1, "claude-opus-4-8", "input_tokens", "0.000015"),
        _row(mig, 9, 2, "claude-opus-4-8", "input_tokens", "0.000015"),
    ]
    _common, delete_ids = mig.plan_common_grid(rows)
    assert 3 not in delete_ids  # exact kept next to the divergent NULL row
    assert 4 not in delete_ids
    assert 7 not in delete_ids  # shields opus from the common exact price
    _assert_unchanged(rows, _apply(mig, rows))


def test_dead_duplicates_are_removed(mig: ModuleType) -> None:
    rows = [
        _row(mig, 1, 1, None, "images", "0.99", provider="photoroom"),  # dead
        _row(mig, 2, 1, None, "images", "0.02", provider="photoroom"),
        _row(mig, 3, 2, None, "images", "0.02", provider="photoroom"),
    ]
    common, delete_ids = mig.plan_common_grid(rows)
    assert common[0].unit_price == Decimal("0.02")
    assert delete_ids == {1, 2, 3}


def test_sonnet_55_common_prices_inserted_once(mig: ModuleType) -> None:
    rows = [_row(mig, 1, None, "claude-sonnet-5", "input_tokens", "0.000003")]
    planned = mig.plan_sonnet_55(rows)
    assert {(p.metric, p.unit_price, p.currency, p.account_id) for p in planned} == {
        ("input_tokens", Decimal("0.000002"), "EUR", None),
        ("output_tokens", Decimal("0.00001"), "EUR", None),
    }
    rows.append(_row(mig, 2, None, "claude-sonnet-5-5", "input_tokens", "0.000002"))
    assert [p.metric for p in mig.plan_sonnet_55(rows)] == ["output_tokens"]


def test_downgrade_copies_preserve_resolution(mig: ModuleType) -> None:
    rows = [
        _row(mig, 1, None, "claude-sonnet-5", "input_tokens", "0.000003"),
        _row(mig, 2, None, None, "output_tokens", "0.000015"),
        _row(mig, 3, 2, None, "input_tokens", "0.000001"),  # exception
    ]
    copies = mig.plan_account_copies(rows, [1, 2])
    assert {(c.account_id, c.model, c.metric) for c in copies} == {
        (1, "claude-sonnet-5", "input_tokens"),
        (1, None, "output_tokens"),
        # account 2: sonnet exact NOT copied (its NULL exception came first)
        (2, None, "output_tokens"),
    }
    flat = [r for r in rows if r.account_id is not None] + [
        _row(mig, 100 + i, c.account_id, c.model, c.metric, str(c.unit_price))
        for i, c in enumerate(copies)
    ]
    for account_id in (1, 2):
        for key in (
            ("claude", "claude-sonnet-5", "input_tokens"),
            ("claude", "other", "output_tokens"),
        ):
            assert _resolve(flat, account_id, key) == _resolve(rows, account_id, key)
