"""Tests for the usage reporting routes (/usage): prices, summary, by-job, CSV."""

from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from fastapi.testclient import TestClient
from sqlalchemy import select, update

from app.api.deps import get_db
from app.main import app
from app.models import Account, EnrichmentJob, UsageEvent, UsagePrice


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


def _seed_event(
    *,
    account_id: int,
    metric: str,
    quantity: int,
    provider: str = "claude",
    model: str | None = None,
    job_id: int | None = None,
    source: str = "enrichment",
    created_at: datetime | None = None,
) -> int:
    db = _db()
    event = UsageEvent(
        account_id=account_id,
        job_id=job_id,
        source=source,
        provider=provider,
        model=model,
        metric=metric,
        quantity=quantity,
    )
    db.add(event)
    db.commit()
    if created_at is not None:
        # created_at is server_default: antidate it directly in SQL.
        db.execute(
            update(UsageEvent)
            .where(UsageEvent.id == event.id)
            .values(created_at=created_at)
        )
        db.commit()
    event_id: int = event.id
    return event_id


def _seed_job(
    *, account_id: int, job_type: str, selection: dict[str, Any] | None = None
) -> int:
    db = _db()
    job = EnrichmentJob(
        account_id=account_id,
        job_type=job_type,
        selection_json=selection or {},
        config_json={},
    )
    db.add(job)
    db.commit()
    job_id: int = job.id
    return job_id


def _post_price(
    client: TestClient,
    *,
    provider: str = "claude",
    model: str | None = None,
    metric: str = "input_tokens",
    unit_price: str = "0.000003",
) -> dict[str, Any]:
    response = client.post(
        "/usage/prices",
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


def _current_month() -> str:
    now = datetime.now(UTC)
    return f"{now.year:04d}-{now.month:02d}"


def _previous_month_dt() -> datetime:
    now = datetime.now(UTC)
    if now.month == 1:
        return datetime(now.year - 1, 12, 15, tzinfo=UTC)
    return datetime(now.year, now.month - 1, 15, tzinfo=UTC)


def test_usage_requires_authentication(client: TestClient) -> None:
    assert client.get("/usage/prices").status_code == 401
    assert client.get("/usage/summary").status_code == 401
    assert client.get("/usage/by-job").status_code == 401
    assert client.get("/usage/export").status_code == 401


def test_price_crud(auth_client: TestClient) -> None:
    created = _post_price(auth_client, model="claude-sonnet-4-5", unit_price="0.000003")
    assert created["provider"] == "claude"
    assert created["model"] == "claude-sonnet-4-5"
    assert created["metric"] == "input_tokens"
    assert created["currency"] == "EUR"
    assert Decimal(created["unit_price"]) == Decimal("0.000003")

    # Fallback price (model null) and another metric; list is sorted
    # provider/model/metric with the model-null fallback first.
    _post_price(auth_client, model=None, metric="output_tokens", unit_price="0.000015")
    _post_price(auth_client, model=None, metric="input_tokens", unit_price="0.000001")

    listed = auth_client.get("/usage/prices").json()
    assert [(p["model"], p["metric"]) for p in listed] == [
        (None, "input_tokens"),
        (None, "output_tokens"),
        ("claude-sonnet-4-5", "input_tokens"),
    ]

    # Partial update.
    patched = auth_client.patch(
        f"/usage/prices/{created['id']}", json={"unit_price": "0.000006"}
    )
    assert patched.status_code == 200
    assert Decimal(patched.json()["unit_price"]) == Decimal("0.000006")
    assert patched.json()["model"] == "claude-sonnet-4-5"  # untouched

    # Delete.
    assert auth_client.delete(f"/usage/prices/{created['id']}").status_code == 204
    remaining = auth_client.get("/usage/prices").json()
    assert created["id"] not in [p["id"] for p in remaining]


def test_price_account_isolation(auth_client: TestClient) -> None:
    _account_id(auth_client)  # resolve the caller's account first
    db = _db()
    other = Account(name="other-boutique")
    db.add(other)
    db.flush()
    foreign = UsagePrice(
        account_id=other.id,
        provider="claude",
        model=None,
        metric="input_tokens",
        unit_price=Decimal("0.000001"),
    )
    db.add(foreign)
    db.commit()
    foreign_id = foreign.id

    assert auth_client.get("/usage/prices").json() == []
    patch = auth_client.patch(f"/usage/prices/{foreign_id}", json={"unit_price": "0.5"})
    assert patch.status_code == 404
    assert patch.json()["code"] == "not_found"
    assert auth_client.delete(f"/usage/prices/{foreign_id}").status_code == 404


def test_summary_pricing_fallback_and_coefficient(auth_client: TestClient) -> None:
    account_id = _account_id(auth_client)
    # Exact price for model-a input, provider-wide fallback for input, no
    # price at all for output_tokens.
    _post_price(
        auth_client, model="model-a", metric="input_tokens", unit_price="0.000003"
    )
    _post_price(auth_client, model=None, metric="input_tokens", unit_price="0.000001")

    # billing_coefficient persists through the regular settings PUT.
    put = auth_client.put("/settings/account", json={"billing_coefficient": 2.0})
    assert put.status_code == 200
    assert put.json()["billing_coefficient"] == 2.0
    assert auth_client.get("/settings/account").json()["billing_coefficient"] == 2.0

    # Two events on the same group: quantities are summed.
    _seed_event(
        account_id=account_id, model="model-a", metric="input_tokens", quantity=400
    )
    _seed_event(
        account_id=account_id, model="model-a", metric="input_tokens", quantity=600
    )
    _seed_event(
        account_id=account_id, model="model-a", metric="output_tokens", quantity=500
    )
    _seed_event(
        account_id=account_id, model="model-b", metric="input_tokens", quantity=2000
    )
    # Previous-month event: excluded from the current-month summary.
    _seed_event(
        account_id=account_id,
        model="model-a",
        metric="input_tokens",
        quantity=99999,
        created_at=_previous_month_dt(),
    )

    response = auth_client.get("/usage/summary")
    assert response.status_code == 200
    summary = response.json()
    assert summary["month"] == _current_month()
    assert summary["currency"] == "EUR"
    assert summary["coefficient"] == 2.0
    assert summary["unpriced_count"] == 1

    lines = {(line["model"], line["metric"]): line for line in summary["lines"]}
    assert len(lines) == 3

    # Exact match wins over the fallback: 1000 × 0.000003 = 0.0030.
    exact = lines[("model-a", "input_tokens")]
    assert exact["quantity"] == 1000
    assert Decimal(exact["unit_price"]) == Decimal("0.000003")
    assert exact["cost"] == "0.0030"
    assert exact["billable"] == "0.0060"  # × coefficient 2.0

    # model-b falls back to the model-null price: 2000 × 0.000001 = 0.0020.
    fallback = lines[("model-b", "input_tokens")]
    assert Decimal(fallback["unit_price"]) == Decimal("0.000001")
    assert fallback["cost"] == "0.0020"
    assert fallback["billable"] == "0.0040"

    # Unpriced line: nulls, counted in unpriced_count, excluded from totals.
    unpriced = lines[("model-a", "output_tokens")]
    assert unpriced["quantity"] == 500
    assert unpriced["unit_price"] is None
    assert unpriced["cost"] is None
    assert unpriced["billable"] is None

    assert summary["totals"] == {"cost": "0.0050", "billable": "0.0100"}

    # Sorted provider/model/metric.
    assert [(line["model"], line["metric"]) for line in summary["lines"]] == [
        ("model-a", "input_tokens"),
        ("model-a", "output_tokens"),
        ("model-b", "input_tokens"),
    ]


def test_summary_explicit_month_filter(auth_client: TestClient) -> None:
    account_id = _account_id(auth_client)
    _post_price(auth_client, model=None, metric="input_tokens", unit_price="0.000001")
    previous = _previous_month_dt()
    _seed_event(
        account_id=account_id,
        metric="input_tokens",
        quantity=1000,
        created_at=previous,
    )
    _seed_event(account_id=account_id, metric="input_tokens", quantity=42)

    month = f"{previous.year:04d}-{previous.month:02d}"
    summary = auth_client.get(f"/usage/summary?month={month}").json()
    assert summary["month"] == month
    assert [line["quantity"] for line in summary["lines"]] == [1000]


def test_by_job_labels_tokens_and_sorting(auth_client: TestClient) -> None:
    account_id = _account_id(auth_client)
    _post_price(auth_client, model=None, metric="input_tokens", unit_price="0.000001")

    import_job = _seed_job(
        account_id=account_id,
        job_type="import",
        selection={"file_name": "commande-espion.pdf", "file_path": "/tmp/x.pdf"},
    )
    enrich_job = _seed_job(account_id=account_id, job_type="enrichment")

    # Import job: highest cost (5000 priced input tokens) + an extra metric.
    _seed_event(
        account_id=account_id,
        job_id=import_job,
        source="import",
        metric="input_tokens",
        quantity=5000,
    )
    _seed_event(
        account_id=account_id,
        job_id=import_job,
        source="import",
        metric="output_tokens",
        quantity=700,
    )
    _seed_event(
        account_id=account_id,
        job_id=import_job,
        source="import",
        metric="web_searches",
        quantity=3,
    )
    # Enrichment job: lower cost (2000 input tokens over two events).
    _seed_event(
        account_id=account_id, job_id=enrich_job, metric="input_tokens", quantity=1500
    )
    _seed_event(
        account_id=account_id, job_id=enrich_job, metric="input_tokens", quantity=500
    )
    # Events without a job: only an unpriced metric → cost null, sorted last.
    _seed_event(account_id=account_id, metric="output_tokens", quantity=900)

    response = auth_client.get("/usage/by-job")
    assert response.status_code == 200
    body = response.json()
    assert body["month"] == _current_month()

    jobs = body["jobs"]
    assert [job["job_id"] for job in jobs] == [import_job, enrich_job, None]

    first = jobs[0]
    assert first["label"] == "commande-espion.pdf"
    assert first["job_type"] == "import"
    assert first["created_at"] is not None
    assert first["input_tokens"] == 5000
    assert first["output_tokens"] == 700
    assert first["other_metrics"] == [
        {"provider": "claude", "metric": "web_searches", "quantity": 3}
    ]
    assert first["cost"] == "0.0050"  # only input_tokens is priced
    assert first["billable"] == "0.0050"  # default coefficient 1.0

    second = jobs[1]
    assert second["label"] == f"Job #{enrich_job}"
    assert second["job_type"] == "enrichment"
    assert second["input_tokens"] == 2000
    assert second["cost"] == "0.0020"

    hors_job = jobs[2]
    assert hors_job["label"] == "Hors job"
    assert hors_job["job_type"] is None
    assert hors_job["created_at"] is None
    assert hors_job["output_tokens"] == 900
    assert hors_job["cost"] is None
    assert hors_job["billable"] is None


def test_export_csv(auth_client: TestClient) -> None:
    account_id = _account_id(auth_client)
    _post_price(auth_client, model=None, metric="input_tokens", unit_price="0.000001")
    _seed_event(account_id=account_id, metric="input_tokens", quantity=3000)
    _seed_event(account_id=account_id, metric="output_tokens", quantity=100)  # unpriced

    month = _current_month()
    response = auth_client.get("/usage/export")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/csv")
    assert (
        response.headers["content-disposition"]
        == f'attachment; filename="consommation_{month}.csv"'
    )

    lines = [line for line in response.text.splitlines() if line]
    assert (
        lines[0]
        == "month,provider,model,metric,quantity,unit_price,cost,coefficient,billable"
    )
    assert lines[-1].split(",")[1] == "TOTAL"
    assert f"{month},TOTAL,,,,,0.0030,1.0,0.0030" == lines[-1]
    # Unpriced row keeps its money cells empty.
    unpriced_row = next(line for line in lines if "output_tokens" in line)
    assert unpriced_row == f"{month},claude,,output_tokens,100,,,1.0,"


def test_invalid_month_returns_422(auth_client: TestClient) -> None:
    for path in ("/usage/summary", "/usage/by-job", "/usage/export"):
        for bad in ("2026-13", "202607", "2026-7", "abcd-ef"):
            response = auth_client.get(f"{path}?month={bad}")
            assert response.status_code == 422, (path, bad)
            assert response.json()["code"] == "invalid_month"
