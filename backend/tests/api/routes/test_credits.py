"""Tests for the prepaid credit system: ledger, grants, guards, hooks."""

from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.api.deps import get_db, get_fashn_client, get_photoroom_client
from app.api.services import credits as credits_service
from app.clients.fashn import FashnClient
from app.clients.photoroom import PhotoroomClient
from app.jobs import queue
from app.main import app
from app.models import Account, CreditEntry, EnrichmentItem, EnrichmentJob


def _db() -> Any:
    return next(app.dependency_overrides[get_db]())


def _account_id(client: TestClient) -> int:
    """Resolve (and lazily create) the signed-in user's account."""
    assert client.get("/settings/account").status_code == 200
    db = _db()
    account = db.scalars(select(Account)).first()
    assert account is not None
    account_id: int = account.id
    return account_id


def _set_settings(account_id: int, **overrides: Any) -> None:
    db = _db()
    account = db.get(Account, account_id)
    account.settings_json = {**(account.settings_json or {}), **overrides}
    db.commit()


def _grant(account_id: int, credits: int, **fields: Any) -> None:
    db = _db()
    db.add(CreditEntry(account_id=account_id, kind="grant", credits=credits, **fields))
    db.commit()


def _entries(account_id: int) -> list[CreditEntry]:
    db = _db()
    return list(
        db.scalars(
            select(CreditEntry)
            .where(CreditEntry.account_id == account_id)
            .order_by(CreditEntry.id)
        ).all()
    )


# --- Client overview ---------------------------------------------------------


def test_credits_overview_defaults(auth_client: TestClient) -> None:
    account_id = _account_id(auth_client)
    response = auth_client.get("/credits")
    assert response.status_code == 200
    body = response.json()
    assert body["balance"] == 0
    assert body["low_credit_threshold"] == 50
    assert body["monthly_free_credits"] == 0
    assert body["packs"] == []
    assert body["month"]["consumed_total"] == 0
    assert body["entries"] == []
    assert _entries(account_id) == []


def test_credits_overview_aggregates_month(auth_client: TestClient) -> None:
    account_id = _account_id(auth_client)
    _grant(account_id, 100, label="Pack 100")
    db = _db()
    credits_service.consume(db, account_id=account_id, action="enrich_item", quantity=3)
    credits_service.consume(
        db, account_id=account_id, action="image_generate", quantity=2
    )
    db.commit()

    body = auth_client.get("/credits").json()
    # 100 - 3×2 - 2×5 = 84
    assert body["balance"] == 84
    assert body["month"]["consumed_total"] == 16
    assert body["month"]["by_action"] == {"enrich_item": 3, "image_generate": 2}
    # Movements list carries the grant, not the consumption rows.
    assert [e["kind"] for e in body["entries"]] == ["grant"]
    assert body["entries"][0]["label"] == "Pack 100"


def test_credits_packs_come_from_settings(auth_client: TestClient) -> None:
    account_id = _account_id(auth_client)
    _set_settings(
        account_id,
        credit_packs=[{"credits": 500, "price_eur": 50.0}],
        low_credit_threshold=20,
    )
    body = auth_client.get("/credits").json()
    assert body["packs"] == [{"credits": 500, "price_eur": 50.0}]
    assert body["low_credit_threshold"] == 20


def test_credits_timeseries_daily_by_action(auth_client: TestClient) -> None:
    account_id = _account_id(auth_client)
    db = _db()
    credits_service.consume(
        db, account_id=account_id, action="image_process", quantity=4
    )
    db.commit()
    body = auth_client.get("/credits/timeseries").json()
    assert [s["key"] for s in body["series"]] == ["Images traitées"]
    points = body["series"][0]["points"]
    assert sum(p["credits"] for p in points) == 4
    # Every day of the month is emitted (0-filled).
    assert len(points) >= 28


# --- Service: grid, consume, subscription ------------------------------------


def test_consume_uses_account_grid_and_traces_unit(
    auth_client: TestClient,
) -> None:
    account_id = _account_id(auth_client)
    _set_settings(account_id, credit_cost_image_generate=7)
    db = _db()
    credits_service.consume(
        db, account_id=account_id, action="image_generate", quantity=2, asset_id=9
    )
    db.commit()
    entry = _entries(account_id)[0]
    assert entry.kind == "consumption"
    assert entry.credits == -14
    assert entry.unit_credits == 7
    assert entry.quantity == 2
    assert entry.asset_id == 9


def test_consume_free_action_writes_nothing(auth_client: TestClient) -> None:
    account_id = _account_id(auth_client)
    _set_settings(account_id, credit_cost_image_process=0)
    db = _db()
    assert (
        credits_service.consume(
            db, account_id=account_id, action="image_process", quantity=1
        )
        is None
    )
    db.commit()
    assert _entries(account_id) == []


def test_subscription_grant_is_lazy_and_idempotent(
    auth_client: TestClient,
) -> None:
    account_id = _account_id(auth_client)
    _set_settings(account_id, monthly_free_credits=50)
    db = _db()
    assert credits_service.balance(db, account_id) == 50
    # A second read in the same month must not grant again.
    assert credits_service.balance(db, account_id) == 50
    entries = _entries(account_id)
    assert len(entries) == 1
    assert entries[0].kind == "subscription"
    assert entries[0].period is not None


def test_dashboard_stats_expose_balance(auth_client: TestClient) -> None:
    account_id = _account_id(auth_client)
    _grant(account_id, 12)
    body = auth_client.get("/stats/dashboard").json()
    assert body["credit_balance"] == 12
    assert body["low_credit_threshold"] == 50


# --- Admin ledger -------------------------------------------------------------


def test_admin_grant_and_ledger(admin_client: TestClient) -> None:
    account_id = _account_id(admin_client)
    response = admin_client.post(
        f"/admin/accounts/{account_id}/credits/grant",
        json={"credits": 500, "kind": "purchase", "label": "Pack 500", "price_eur": 50},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["balance"] == 500
    assert body["entries"][0]["kind"] == "purchase"
    assert body["entries"][0]["price_eur"] == 50

    # Negative adjustment brings the balance back down.
    response = admin_client.post(
        f"/admin/accounts/{account_id}/credits/grant",
        json={"credits": -500, "kind": "adjustment", "label": "Correction"},
    )
    assert response.json()["balance"] == 0

    ledger = admin_client.get(f"/admin/accounts/{account_id}/credits").json()
    assert ledger["balance"] == 0
    assert [e["kind"] for e in ledger["entries"]] == ["adjustment", "purchase"]


def test_admin_grant_rejects_zero(admin_client: TestClient) -> None:
    account_id = _account_id(admin_client)
    response = admin_client.post(
        f"/admin/accounts/{account_id}/credits/grant", json={"credits": 0}
    )
    assert response.status_code == 422


def test_admin_credit_routes_forbidden_for_clients(
    auth_client: TestClient,
) -> None:
    account_id = _account_id(auth_client)
    assert auth_client.get(f"/admin/accounts/{account_id}/credits").status_code == 403
    assert (
        auth_client.post(
            f"/admin/accounts/{account_id}/credits/grant", json={"credits": 10}
        ).status_code
        == 403
    )


def test_credit_settings_are_admin_only(auth_client: TestClient) -> None:
    account_id = _account_id(auth_client)
    _set_settings(account_id, credit_cost_enrich_item=3, monthly_free_credits=50)
    current = auth_client.get("/settings/account").json()
    current["credit_cost_enrich_item"] = 0
    current["monthly_free_credits"] = 9999
    current["credit_packs"] = [{"credits": 1, "price_eur": 0}]
    response = auth_client.put("/settings/account", json=current)
    assert response.status_code == 200
    body = response.json()
    # Client writes must not touch the operator-owned credit fields.
    assert body["credit_cost_enrich_item"] == 3
    assert body["monthly_free_credits"] == 50
    assert body["credit_packs"] == []


# --- Global operator settings ---------------------------------------------------


def test_operator_settings_roundtrip_applies_to_all_accounts(
    admin_client: TestClient,
) -> None:
    account_id = _account_id(admin_client)
    db = _db()
    other = Account(name="boutique-2")
    db.add(other)
    db.commit()
    other_id = other.id

    current = admin_client.get("/admin/settings").json()
    assert current["credit_cost_enrich_item"] == 2  # defaults filled in
    current["credit_cost_enrich_item"] = 3
    current["credit_packs"] = [{"credits": 500, "price_eur": 50.0}]
    # Le jour de facturation est une politique opérateur globale, plus un
    # réglage client (déplacé des Paramètres vers Tarification, 2026-07-16).
    current["billing_day"] = 5
    response = admin_client.put("/admin/settings", json=current)
    assert response.status_code == 200
    assert response.json()["credit_cost_enrich_item"] == 3
    assert response.json()["billing_day"] == 5

    # Both accounts carry the new policy…
    db = _db()
    for acc_id in (account_id, other_id):
        stored = db.get(Account, acc_id).settings_json or {}
        assert stored["credit_cost_enrich_item"] == 3
        assert stored["billing_day"] == 5
        assert stored["credit_packs"] == [{"credits": 500, "price_eur": 50.0}]
    # …and client-facing settings are untouched (defaults still apply).
    assert admin_client.get("/settings/account").json()["meta_max_length"] == 160


def test_operator_settings_admin_only(auth_client: TestClient) -> None:
    assert auth_client.get("/admin/settings").status_code == 403
    assert auth_client.put("/admin/settings", json={}).status_code == 403


def test_admin_credit_timeseries(admin_client: TestClient) -> None:
    account_id = _account_id(admin_client)
    db = _db()
    credits_service.consume(db, account_id=account_id, action="enrich_item", quantity=2)
    db.commit()
    response = admin_client.get(f"/admin/accounts/{account_id}/credits/timeseries")
    assert response.status_code == 200
    body = response.json()
    assert [s["key"] for s in body["series"]] == ["Fiches enrichies"]
    assert sum(p["credits"] for p in body["series"][0]["points"]) == 4


# --- 402 guards on launch routes ----------------------------------------------


def _assert_insufficient(response: httpx.Response) -> None:
    assert response.status_code == 402
    assert response.json()["code"] == "insufficient_credits"


def test_create_job_blocked_without_credits(auth_client: TestClient) -> None:
    _account_id(auth_client)
    response = auth_client.post(
        "/jobs", json={"selection": {"ids": [1, 2]}, "config": {}}
    )
    _assert_insufficient(response)
    db = _db()
    assert db.scalar(select(EnrichmentJob.id)) is None


def test_create_job_passes_with_credits(auth_client: TestClient) -> None:
    account_id = _account_id(auth_client)
    _grant(account_id, 4)  # 2 items × 2 credits
    response = auth_client.post(
        "/jobs", json={"selection": {"ids": [1, 2]}, "config": {}}
    )
    assert response.status_code == 201


def test_create_import_blocked_without_credits(auth_client: TestClient) -> None:
    _account_id(auth_client)
    response = auth_client.post(
        "/imports", files=[("files", ("order.csv", b"ref;ean\n", "text/csv"))]
    )
    _assert_insufficient(response)


def test_normalize_blocked_without_credits(auth_client: TestClient) -> None:
    _account_id(auth_client)
    app.dependency_overrides[get_photoroom_client] = lambda: PhotoroomClient(
        "pr-key", transport=httpx.MockTransport(lambda r: httpx.Response(500))
    )
    try:
        response = auth_client.post(
            "/products/1/images/normalize", json={"image_url": "https://x/img.jpg"}
        )
    finally:
        app.dependency_overrides.pop(get_photoroom_client, None)
    _assert_insufficient(response)


def test_generate_model_blocked_without_credits(auth_client: TestClient) -> None:
    _account_id(auth_client)
    app.dependency_overrides[get_fashn_client] = lambda: FashnClient(
        "fx-key", transport=httpx.MockTransport(lambda r: httpx.Response(500))
    )
    try:
        response = auth_client.post(
            "/products/1/images/generate-model",
            json={"image_url": "https://x/img.jpg", "options": {"num_images": 2}},
        )
    finally:
        app.dependency_overrides.pop(get_fashn_client, None)
    _assert_insufficient(response)


def test_item_normalize_blocked_without_credits(auth_client: TestClient) -> None:
    account_id = _account_id(auth_client)
    db = _db()
    job = EnrichmentJob(account_id=account_id, selection_json={}, config_json={})
    db.add(job)
    db.flush()
    item = EnrichmentItem(job_id=job.id, account_id=account_id, tillin_product_id=1)
    db.add(item)
    db.commit()
    item_id = item.id
    app.dependency_overrides[get_photoroom_client] = lambda: PhotoroomClient(
        "pr-key", transport=httpx.MockTransport(lambda r: httpx.Response(500))
    )
    try:
        response = auth_client.post(
            f"/items/{item_id}/images/normalize",
            json={"url": "https://x/img.jpg"},
        )
    finally:
        app.dependency_overrides.pop(get_photoroom_client, None)
    _assert_insufficient(response)


# --- Consumption hooks ----------------------------------------------------------


@pytest.fixture
def seeded_item(auth_client: TestClient) -> EnrichmentItem:
    account_id = _account_id(auth_client)
    db = _db()
    job = EnrichmentJob(account_id=account_id, selection_json={}, config_json={})
    db.add(job)
    db.flush()
    item = EnrichmentItem(
        job_id=job.id,
        account_id=account_id,
        tillin_product_id=1,
        status="processing",
        attempt_count=3,
    )
    db.add(item)
    db.commit()
    db.refresh(item)
    return item


def test_complete_item_debits_enrich_credits(seeded_item: EnrichmentItem) -> None:
    db = _db()
    item = db.get(EnrichmentItem, seeded_item.id)
    queue.complete_item(db, item)
    entries = _entries(item.account_id)
    assert len(entries) == 1
    assert entries[0].action == "enrich_item"
    assert entries[0].credits == -2
    assert entries[0].item_id == item.id
    assert entries[0].job_id == item.job_id


def test_fail_item_debits_nothing(seeded_item: EnrichmentItem) -> None:
    db = _db()
    item = db.get(EnrichmentItem, seeded_item.id)
    queue.fail_item(db, item, "boom")
    assert _entries(item.account_id) == []
