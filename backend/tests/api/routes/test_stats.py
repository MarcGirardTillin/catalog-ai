"""Tests for the dashboard statistics route."""

from datetime import UTC, datetime, timedelta

from fastapi.testclient import TestClient


def test_stats_require_authentication(client: TestClient) -> None:
    assert client.get("/stats/dashboard").status_code == 401


def test_dashboard_stats_empty_account(auth_client: TestClient) -> None:
    response = auth_client.get("/stats/dashboard")
    assert response.status_code == 200
    body = response.json()
    assert body["applied_items"] == 0
    assert body["jobs_total"] == 0
    assert body["avg_item_seconds"] is None
    assert body["auto_resolve_rate"] is None


def test_dashboard_stats_aggregates(auth_client: TestClient) -> None:
    # One job, three items in different states.
    response = auth_client.post("/jobs", json={"selection": {"ids": [1, 2, 3]}})
    assert response.status_code == 201

    from app.api.deps import get_db
    from app.main import app
    from app.models import EnrichmentItem

    db = next(app.dependency_overrides[get_db]())
    items = db.query(EnrichmentItem).order_by(EnrichmentItem.id).all()
    start = datetime.now(UTC)

    items[0].status = "applied"
    items[0].source_method = "shopify_json"
    items[0].started_at = start
    items[0].finished_at = start + timedelta(seconds=10)

    items[1].status = "ready_for_review"
    items[1].source_method = "needs_manual"
    items[1].started_at = start
    items[1].finished_at = start + timedelta(seconds=20)

    items[2].status = "pending"  # not settled: excluded from rates/timing
    db.commit()

    body = auth_client.get("/stats/dashboard").json()
    assert body["applied_items"] == 1
    assert body["ready_items"] == 1
    assert body["items_total"] == 3
    assert body["jobs_total"] == 1
    assert body["running_jobs"] == 1  # job still has a pending item
    assert body["avg_item_seconds"] == 15.0
    assert body["auto_resolve_rate"] == 0.5
