"""Common supplier cost grid + per-account exceptions (admin-only).

Resolution for an account's event: account exact → account model-NULL →
common exact → common model-NULL → no price.
"""

from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from fastapi.testclient import TestClient
from sqlalchemy import select, update

from app.api.deps import get_db
from app.api.routes import usage as usage_module
from app.api.services.usage_pricing import PriceGrid, grid_from_snapshot
from app.main import app
from app.models import Account, UsageBillingSnapshot, UsageEvent, UsagePrice


def _db() -> Any:
    return next(app.dependency_overrides[get_db]())


def _account_id(client: TestClient) -> int:
    assert client.get("/settings/account").status_code == 200
    account = _db().scalars(select(Account)).first()
    assert account is not None
    account_id: int = account.id
    return account_id


def _other_account() -> int:
    db = _db()
    other = Account(name="autre-boutique")
    db.add(other)
    db.commit()
    other_id: int = other.id
    return other_id


def _event(
    account_id: int,
    *,
    model: str | None,
    metric: str = "input_tokens",
    quantity: int = 1_000_000,
    provider: str = "claude",
    created_at: datetime | None = None,
) -> None:
    db = _db()
    event = UsageEvent(
        account_id=account_id,
        source="enrichment",
        provider=provider,
        model=model,
        metric=metric,
        quantity=quantity,
    )
    db.add(event)
    db.commit()
    if created_at is not None:
        db.execute(
            update(UsageEvent)
            .where(UsageEvent.id == event.id)
            .values(created_at=created_at)
        )
        db.commit()


def _price(
    client: TestClient,
    url: str,
    *,
    model: str | None,
    unit_price: str,
    metric: str = "input_tokens",
    provider: str = "claude",
) -> dict[str, Any]:
    response = client.post(
        url,
        json={
            "provider": provider,
            "model": model,
            "metric": metric,
            "unit_price": unit_price,
        },
    )
    assert response.status_code == 201, response.text
    body: dict[str, Any] = response.json()
    return body


def _unit_prices(summary: dict[str, Any]) -> dict[str | None, str | None]:
    return {line["model"]: line["unit_price"] for line in summary["lines"]}


# --- Pure resolution -------------------------------------------------------


def test_price_grid_cascade_order() -> None:
    d = Decimal
    grid = PriceGrid(
        account={("claude", None, "in"): d("4")},
        common={("claude", "m", "in"): d("2"), ("claude", None, "in"): d("1")},
    )
    # Account model-NULL exception beats the common exact price.
    assert grid.resolve("claude", "m", "in") == d("4")
    only_common = PriceGrid(account={}, common=grid.common)
    assert only_common.resolve("claude", "m", "in") == d("2")
    assert only_common.resolve("claude", "other", "in") == d("1")
    assert only_common.resolve("claude", "m", "out") is None
    exact = PriceGrid(
        account={("claude", "m", "in"): d("9"), ("claude", None, "in"): d("4")},
        common=grid.common,
    )
    assert exact.resolve("claude", "m", "in") == d("9")
    assert exact.resolve("claude", "x", "in") == d("4")


def test_legacy_snapshot_rows_are_account_scoped() -> None:
    grid = grid_from_snapshot(
        [
            {
                "provider": "claude",
                "model": None,
                "metric": "in",
                "unit_price": "0.1",
                "currency": "EUR",
            }
        ]
    )
    assert grid.account == {("claude", None, "in"): Decimal("0.1")}
    assert grid.common == {}


# --- Routes ------------------------------------------------------------------


def test_common_grid_applies_to_every_account(admin_client: TestClient) -> None:
    """An account without any exception is priced by the common grid alone."""
    _account_id(admin_client)
    other = _other_account()
    _price(
        admin_client, "/usage/prices", model="claude-sonnet-5", unit_price="0.000003"
    )
    _price(admin_client, "/usage/prices", model=None, unit_price="0.000001")
    _event(other, model="claude-sonnet-5")
    _event(other, model="claude-haiku-4-5")

    db = _db()
    stored = db.scalars(select(UsagePrice)).all()
    assert all(p.account_id is None for p in stored)

    summary = admin_client.get(f"/admin/accounts/{other}/usage").json()
    assert summary["unpriced_count"] == 0
    prices = _unit_prices(summary)
    assert Decimal(prices["claude-sonnet-5"] or "") == Decimal("0.000003")
    assert Decimal(prices["claude-haiku-4-5"] or "") == Decimal("0.000001")
    assert summary["totals"]["cost"] == "4.0000"


def test_account_exception_overrides_common_price(admin_client: TestClient) -> None:
    own = _account_id(admin_client)
    other = _other_account()
    _price(
        admin_client, "/usage/prices", model="claude-sonnet-5", unit_price="0.000003"
    )
    _price(admin_client, "/usage/prices", model=None, unit_price="0.000001")
    for account_id in (own, other):
        _event(account_id, model="claude-sonnet-5")
        _event(account_id, model="claude-haiku-4-5")

    # Model-NULL exception on `other`: it beats BOTH common rows.
    created = _price(
        admin_client,
        f"/admin/accounts/{other}/prices",
        model=None,
        unit_price="0.0000005",
    )
    assert created["common_unit_price"] is not None
    assert Decimal(created["common_unit_price"]) == Decimal("0.000001")

    other_prices = _unit_prices(
        admin_client.get(f"/admin/accounts/{other}/usage").json()
    )
    assert Decimal(other_prices["claude-sonnet-5"] or "") == Decimal("0.0000005")
    assert Decimal(other_prices["claude-haiku-4-5"] or "") == Decimal("0.0000005")

    # The caller's account keeps the common grid.
    own_prices = _unit_prices(admin_client.get("/usage/summary").json())
    assert Decimal(own_prices["claude-sonnet-5"] or "") == Decimal("0.000003")

    # Exceptions are listed per account, never in the common grid.
    listed = admin_client.get(f"/admin/accounts/{other}/prices").json()
    assert [p["id"] for p in listed] == [created["id"]]
    assert created["id"] not in [
        p["id"] for p in admin_client.get("/usage/prices").json()
    ]
    assert admin_client.get(f"/admin/accounts/{own}/prices").json() == []

    # Update then delete: the account falls back to the common grid.
    patched = admin_client.patch(
        f"/admin/accounts/{other}/prices/{created['id']}",
        json={"model": "claude-sonnet-5", "unit_price": "0.0000025"},
    )
    assert patched.status_code == 200, patched.text
    assert Decimal(patched.json()["common_unit_price"]) == Decimal("0.000003")
    other_prices = _unit_prices(
        admin_client.get(f"/admin/accounts/{other}/usage").json()
    )
    assert Decimal(other_prices["claude-sonnet-5"] or "") == Decimal("0.0000025")
    assert Decimal(other_prices["claude-haiku-4-5"] or "") == Decimal("0.000001")

    assert (
        admin_client.delete(
            f"/admin/accounts/{other}/prices/{created['id']}"
        ).status_code
        == 204
    )
    other_prices = _unit_prices(
        admin_client.get(f"/admin/accounts/{other}/usage").json()
    )
    assert Decimal(other_prices["claude-sonnet-5"] or "") == Decimal("0.000003")


def test_scopes_are_isolated(admin_client: TestClient) -> None:
    own = _account_id(admin_client)
    other = _other_account()
    common = _price(admin_client, "/usage/prices", model=None, unit_price="0.1")
    exception = _price(
        admin_client, f"/admin/accounts/{other}/prices", model=None, unit_price="0.2"
    )
    # The common CRUD never reaches an exception…
    assert admin_client.delete(f"/usage/prices/{exception['id']}").status_code == 404
    # …an account route never reaches the common grid or another account.
    assert (
        admin_client.patch(
            f"/admin/accounts/{other}/prices/{common['id']}", json={"unit_price": "1"}
        ).status_code
        == 404
    )
    assert (
        admin_client.delete(
            f"/admin/accounts/{own}/prices/{exception['id']}"
        ).status_code
        == 404
    )
    assert admin_client.get("/admin/accounts/999999/prices").status_code == 404


def test_duplicate_keys_rejected(admin_client: TestClient) -> None:
    _account_id(admin_client)
    other = _other_account()
    _price(admin_client, "/usage/prices", model=None, unit_price="0.1")
    dup = admin_client.post(
        "/usage/prices",
        json={
            "provider": "claude",
            "model": None,
            "metric": "input_tokens",
            "unit_price": "0.3",
        },
    )
    assert dup.status_code == 409
    assert dup.json()["code"] == "duplicate_price"
    # Same key as an exception is fine (that is what an exception is)…
    _price(
        admin_client, f"/admin/accounts/{other}/prices", model=None, unit_price="0.2"
    )
    # …but only once per account.
    again = admin_client.post(
        f"/admin/accounts/{other}/prices",
        json={
            "provider": "claude",
            "model": None,
            "metric": "input_tokens",
            "unit_price": "0.4",
        },
    )
    assert again.status_code == 409
    # Patching a row onto an existing key is refused too.
    second = _price(admin_client, "/usage/prices", model="m", unit_price="0.5")
    clash = admin_client.patch(f"/usage/prices/{second['id']}", json={"model": None})
    assert clash.status_code == 409


def test_frozen_month_pins_common_and_exception_prices(
    admin_client: TestClient, monkeypatch: Any
) -> None:
    monkeypatch.setattr(usage_module, "_now", lambda: datetime(2026, 8, 15, tzinfo=UTC))
    _account_id(admin_client)
    other = _other_account()
    common = _price(admin_client, "/usage/prices", model="m", unit_price="0.000003")
    _price(
        admin_client,
        f"/admin/accounts/{other}/prices",
        model=None,
        unit_price="0.000001",
    )
    _event(
        other, model="m", quantity=1000, created_at=datetime(2026, 6, 10, tzinfo=UTC)
    )
    _event(
        other, model="z", quantity=1000, created_at=datetime(2026, 6, 10, tzinfo=UTC)
    )

    first = admin_client.get(f"/admin/accounts/{other}/usage?month=2026-06").json()
    assert first["frozen"] is True
    # Account NULL exception wins over the common exact price on both lines.
    assert first["totals"]["cost"] == "0.0020"

    snapshot = (
        _db()
        .scalars(
            select(UsageBillingSnapshot).where(UsageBillingSnapshot.account_id == other)
        )
        .one()
    )
    assert {row["scope"] for row in snapshot.prices_json} == {"account", "common"}

    # Repricing the common grid leaves the billed month untouched.
    admin_client.patch(f"/usage/prices/{common['id']}", json={"unit_price": "1"})
    again = admin_client.get(f"/admin/accounts/{other}/usage?month=2026-06").json()
    assert again["totals"]["cost"] == "0.0020"


def test_usage_metrics_priced_against_common_grid(admin_client: TestClient) -> None:
    _account_id(admin_client)
    other = _other_account()
    _event(other, model="m")
    _price(admin_client, f"/admin/accounts/{other}/prices", model=None, unit_price="1")
    metrics = admin_client.get("/admin/usage-metrics").json()
    assert [m["priced"] for m in metrics] == [False]  # exception ≠ common price
    _price(admin_client, "/usage/prices", model=None, unit_price="1")
    metrics = admin_client.get("/admin/usage-metrics").json()
    assert [m["priced"] for m in metrics] == [True]


def test_price_routes_forbidden_for_regular_user(auth_client: TestClient) -> None:
    body = {"provider": "claude", "model": None, "metric": "x", "unit_price": "1"}
    assert auth_client.get("/usage/prices").status_code == 403
    assert auth_client.post("/usage/prices", json=body).status_code == 403
    assert auth_client.patch("/usage/prices/1", json={}).status_code == 403
    assert auth_client.delete("/usage/prices/1").status_code == 403
    assert auth_client.get("/admin/accounts/1/prices").status_code == 403
    assert auth_client.post("/admin/accounts/1/prices", json=body).status_code == 403
    assert auth_client.patch("/admin/accounts/1/prices/1", json={}).status_code == 403
    assert auth_client.delete("/admin/accounts/1/prices/1").status_code == 403
