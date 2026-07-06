"""Tests for enrichment job and item routes."""

from typing import Any

from fastapi.testclient import TestClient


def _create_job(client: TestClient, ids: list[int]) -> dict[str, Any]:
    response = client.post(
        "/jobs", json={"selection": {"ids": ids}, "config": {"translate": True}}
    )
    assert response.status_code == 201
    body: dict[str, Any] = response.json()
    return body


def test_jobs_require_authentication(client: TestClient) -> None:
    assert client.get("/jobs").status_code == 401
    assert client.post("/jobs", json={"selection": {"ids": [1]}}).status_code == 401


def test_create_job_with_ids_creates_items(auth_client: TestClient) -> None:
    job = _create_job(auth_client, [101, 102, 103])

    assert job["status"] == "pending"
    assert job["counts"]["total"] == 3
    assert job["counts"]["pending"] == 3
    assert job["selection_json"] == {"ids": [101, 102, 103]}
    assert job["config_json"] == {"translate": True}


def test_create_job_requires_ids_xor_tag(auth_client: TestClient) -> None:
    both = auth_client.post("/jobs", json={"selection": {"ids": [1], "tag": "ss25"}})
    neither = auth_client.post("/jobs", json={"selection": {}})

    assert both.status_code == 422
    assert neither.status_code == 422


def test_create_job_with_tag_has_no_items_yet(auth_client: TestClient) -> None:
    response = auth_client.post("/jobs", json={"selection": {"tag": "ss25"}})

    assert response.status_code == 201
    assert response.json()["counts"]["total"] == 0


def test_list_and_detail_jobs(auth_client: TestClient) -> None:
    first = _create_job(auth_client, [1])
    second = _create_job(auth_client, [2, 3])

    listing = auth_client.get("/jobs")
    assert listing.status_code == 200
    body = listing.json()
    assert body["total"] == 2
    # Newest first.
    assert [job["id"] for job in body["items"]] == [second["id"], first["id"]]

    detail = auth_client.get(f"/jobs/{second['id']}")
    assert detail.status_code == 200
    assert detail.json()["counts"]["total"] == 2

    assert auth_client.get("/jobs/99999").status_code == 404


def _first_item_id(auth_client: TestClient, job: dict[str, Any]) -> int:
    # Items are created sequentially with the job; find one via detail counts.
    # The API exposes items individually; ids start at 1 in a fresh test DB.
    for candidate in range(1, 10):
        response = auth_client.get(f"/items/{candidate}")
        if response.status_code == 200 and response.json()["job_id"] == job["id"]:
            return candidate
    raise AssertionError("No item found for job")


def test_item_review_flow(auth_client: TestClient) -> None:
    job = _create_job(auth_client, [42])
    item_id = _first_item_id(auth_client, job)

    # pending items cannot be edited or approved.
    assert (
        auth_client.patch(f"/items/{item_id}", json={"staged_title": "X"}).status_code
        == 409
    )
    assert auth_client.post(f"/items/{item_id}/approve").status_code == 409

    # Simulate the worker staging a result.
    from app.api.deps import get_db
    from app.main import app
    from app.models import EnrichmentItem

    override = app.dependency_overrides[get_db]
    db = next(override())
    db_item = db.get(EnrichmentItem, item_id)
    assert db_item is not None
    db_item.status = "ready_for_review"
    db.commit()

    patched = auth_client.patch(
        f"/items/{item_id}", json={"staged_title": "Nouveau titre"}
    )
    assert patched.status_code == 200
    assert patched.json()["staged_title"] == "Nouveau titre"

    approved = auth_client.post(f"/items/{item_id}/approve")
    assert approved.status_code == 200
    assert approved.json()["status"] == "approved"

    # approve -> reject is allowed (change of mind before apply).
    rejected = auth_client.post(f"/items/{item_id}/reject")
    assert rejected.status_code == 200
    assert rejected.json()["status"] == "rejected"

    # rejected is terminal for review actions.
    assert auth_client.post(f"/items/{item_id}/approve").status_code == 409

    counts = auth_client.get(f"/jobs/{job['id']}").json()["counts"]
    assert counts["rejected"] == 1


def test_list_job_items_with_status_filter(auth_client: TestClient) -> None:
    job = _create_job(auth_client, [11, 12, 13])

    listing = auth_client.get(f"/jobs/{job['id']}/items")
    assert listing.status_code == 200
    body = listing.json()
    assert body["total"] == 3
    assert [i["tillin_product_id"] for i in body["items"]] == [11, 12, 13]
    assert all(i["status"] == "pending" for i in body["items"])

    # Stage one item, then filter by status.
    from app.api.deps import get_db
    from app.main import app
    from app.models import EnrichmentItem

    override = app.dependency_overrides[get_db]
    db = next(override())
    db_item = db.get(EnrichmentItem, body["items"][0]["id"])
    assert db_item is not None
    db_item.status = "ready_for_review"
    db_item.staged_title = "Titre stagé"
    db.commit()

    ready = auth_client.get(
        f"/jobs/{job['id']}/items", params={"status": "ready_for_review"}
    )
    assert ready.status_code == 200
    assert ready.json()["total"] == 1
    assert ready.json()["items"][0]["staged_title"] == "Titre stagé"

    assert auth_client.get("/jobs/99999/items").status_code == 404
