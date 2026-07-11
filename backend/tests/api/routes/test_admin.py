"""Tests for the admin console: role gating, white-label redaction, monitoring.

The white-label contract: a NON-admin response must never contain provider or
model names (claude/photoroom/…), raw costs, unit prices or the billing
coefficient — hiding in the UI is not enough, the payloads must be clean.
"""

from typing import Any

from fastapi.testclient import TestClient
from sqlalchemy import select

from app.api.deps import get_db
from app.main import app
from app.models import Account, EnrichmentJob, ImportItem, UsageEvent, UsagePrice

FORBIDDEN_WORDS = ("claude", "photoroom", "fashn", "firecrawl", "openai")


def _db() -> Any:
    return next(app.dependency_overrides[get_db]())


def _account_id(client: TestClient) -> int:
    assert client.get("/settings/account").status_code == 200
    db = _db()
    account = db.scalars(select(Account)).first()
    assert account is not None
    account_id: int = account.id
    return account_id


def _seed_priced_events(account_id: int) -> None:
    """Two providers, one priced metric each (priced directly in DB — a
    regular user cannot reach the price CRUD)."""
    db = _db()
    db.add(
        UsagePrice(
            account_id=account_id,
            provider="claude",
            model=None,
            metric="input_tokens",
            unit_price="0.000001",
            currency="EUR",
        )
    )
    db.add(
        UsagePrice(
            account_id=account_id,
            provider="photoroom",
            model=None,
            metric="images",
            unit_price="0.02",
            currency="EUR",
        )
    )
    db.add(
        UsageEvent(
            account_id=account_id,
            source="enrichment",
            provider="claude",
            model="claude-opus-4-8",
            metric="input_tokens",
            quantity=1_000_000,
        )
    )
    db.add(
        UsageEvent(
            account_id=account_id,
            source="enrichment",
            provider="claude",
            model="claude-haiku-4-5",
            metric="input_tokens",
            quantity=500_000,
        )
    )
    db.add(
        UsageEvent(
            account_id=account_id,
            source="imaging",
            provider="photoroom",
            model="photoroom-v2",
            metric="images",
            quantity=10,
        )
    )
    db.commit()


# --- Role gating -------------------------------------------------------------


def test_admin_routes_forbidden_for_regular_user(auth_client: TestClient) -> None:
    assert auth_client.get("/admin/accounts").status_code == 403
    assert auth_client.get("/admin/overview").status_code == 403
    assert auth_client.get("/admin/accounts/1/usage").status_code == 403
    assert auth_client.get("/admin/accounts/1/usage/by-job").status_code == 403
    assert auth_client.get("/admin/accounts/1/activity").status_code == 403
    assert auth_client.get("/admin/accounts/1/settings").status_code == 403
    assert auth_client.put("/admin/accounts/1/settings", json={}).status_code == 403


def test_usage_admin_surfaces_forbidden_for_regular_user(
    auth_client: TestClient,
) -> None:
    assert auth_client.get("/usage/prices").status_code == 403
    body = {"provider": "claude", "model": None, "metric": "x", "unit_price": "1"}
    assert auth_client.post("/usage/prices", json=body).status_code == 403
    assert auth_client.patch("/usage/prices/1", json={}).status_code == 403
    assert auth_client.delete("/usage/prices/1").status_code == 403
    assert auth_client.post("/usage/snapshot?month=2026-01").status_code == 403
    assert auth_client.get("/usage/timeseries?group_by=model").status_code == 403
    assert auth_client.get("/usage/timeseries?group_by=provider").status_code == 403
    # The total curve stays available to clients.
    assert auth_client.get("/usage/timeseries?group_by=none").status_code == 200


def test_me_exposes_is_admin_flag(
    auth_client: TestClient,
) -> None:
    assert auth_client.get("/auth/me").json()["is_admin"] is False


def test_me_exposes_is_admin_flag_admin(admin_client: TestClient) -> None:
    assert admin_client.get("/auth/me").json()["is_admin"] is True


# --- White-label redaction ---------------------------------------------------


def test_client_summary_is_redacted(auth_client: TestClient) -> None:
    account_id = _account_id(auth_client)
    _seed_priced_events(account_id)

    body = auth_client.get("/usage/summary").json()
    # Coefficient neutralized; raw cost mirrors billable (never the raw sum).
    assert body["coefficient"] == 1.0
    assert body["totals"]["cost"] == body["totals"]["billable"]
    # Two claude models MERGE into one neutral line (models must not leak,
    # not even their count).
    text_lines = [
        line for line in body["lines"] if line["provider"] == "Génération de texte"
    ]
    assert len(text_lines) == 1
    assert text_lines[0]["quantity"] == 1_500_000
    assert text_lines[0]["model"] is None
    assert text_lines[0]["unit_price"] is None
    assert text_lines[0]["cost"] is None
    assert text_lines[0]["billable"] == "1.5000"
    image_lines = [
        line for line in body["lines"] if line["provider"] == "Traitement d'image"
    ]
    assert len(image_lines) == 1 and image_lines[0]["billable"] == "0.2000"
    # No provider/model name anywhere in the payload.
    raw = str(body).lower()
    assert not any(word in raw for word in FORBIDDEN_WORDS)


def test_admin_summary_is_not_redacted(admin_client: TestClient) -> None:
    account_id = _account_id(admin_client)
    _seed_priced_events(account_id)
    body = admin_client.get("/usage/summary").json()
    models = {line["model"] for line in body["lines"]}
    assert "claude-opus-4-8" in models
    assert any(line["cost"] is not None for line in body["lines"])


def test_client_by_job_and_export_are_redacted(auth_client: TestClient) -> None:
    account_id = _account_id(auth_client)
    _seed_priced_events(account_id)

    by_job = auth_client.get("/usage/by-job").json()
    raw = str(by_job).lower()
    assert not any(word in raw for word in FORBIDDEN_WORDS)
    for line in by_job["jobs"]:
        assert line["cost"] is None

    export = auth_client.get("/usage/export")
    assert export.status_code == 200
    csv_text = export.text.lower()
    assert not any(word in csv_text for word in FORBIDDEN_WORDS)
    assert "unit_price" not in csv_text and "coefficient" not in csv_text
    assert csv_text.splitlines()[0] == "month,service,metric,quantity,amount"


# --- Admin monitoring --------------------------------------------------------


def test_admin_overview_margin_and_volumes(admin_client: TestClient) -> None:
    account_id = _account_id(admin_client)
    _seed_priced_events(account_id)
    # Coefficient 2.0 via the admin settings route → margin = billable - cost.
    settings = admin_client.get(f"/admin/accounts/{account_id}/settings").json()
    settings["billing_coefficient"] = 2.0
    put = admin_client.put(f"/admin/accounts/{account_id}/settings", json=settings)
    assert put.status_code == 200

    db = _db()
    job = EnrichmentJob(
        account_id=account_id, job_type="import", selection_json={}, config_json={}
    )
    db.add(job)
    db.commit()
    db.add(
        ImportItem(
            account_id=account_id, job_id=job.id, payload_json={}, status="failed"
        )
    )
    db.commit()

    overview = admin_client.get("/admin/overview").json()
    line = next(
        entry for entry in overview["lines"] if entry["account_id"] == account_id
    )
    assert line["coefficient"] == 2.0
    assert line["cost"] == "1.7000"
    assert line["billable"] == "3.4000"
    assert line["margin"] == "1.7000"
    assert line["imports_count"] == 1
    assert line["failed_items"] == 1

    accounts = admin_client.get("/admin/accounts").json()
    assert any(acc["id"] == account_id for acc in accounts)

    activity = admin_client.get(f"/admin/accounts/{account_id}/activity").json()
    assert activity["entries"][0]["job_type"] == "import"
    assert activity["entries"][0]["failed_items"] == 1

    full = admin_client.get(f"/admin/accounts/{account_id}/usage").json()
    assert any(line["model"] == "claude-opus-4-8" for line in full["lines"])


def test_client_settings_put_cannot_touch_admin_fields(
    auth_client: TestClient,
) -> None:
    _account_id(auth_client)
    put = auth_client.put(
        "/settings/account",
        json={
            "billing_coefficient": 9.0,
            "minutes_saved_per_import_product": 99,
            "minutes_saved_per_enriched_product": 99,
        },
    )
    assert put.status_code == 200
    stored = auth_client.get("/settings/account").json()
    assert stored["billing_coefficient"] == 1.0
    assert stored["minutes_saved_per_import_product"] == 2
    assert stored["minutes_saved_per_enriched_product"] == 10
