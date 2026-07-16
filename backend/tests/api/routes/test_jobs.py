"""Tests for enrichment job and item routes."""

from typing import Any

import pytest
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


def test_create_job_schedules_background_runner(auth_client: TestClient) -> None:
    from app.api.deps import get_job_runner
    from app.main import app

    seen: list[int] = []
    app.dependency_overrides[get_job_runner] = lambda: seen.append
    try:
        job = _create_job(auth_client, [201, 202])
    finally:
        # Restore the fixture's default no-op runner.
        app.dependency_overrides[get_job_runner] = lambda: lambda job_id: None

    assert seen == [job["id"]]


def test_job_reports_duration_after_worker_settles(auth_client: TestClient) -> None:
    from app.api.deps import get_db
    from app.jobs.worker import process_one
    from app.main import app
    from app.models import EnrichmentItem

    job = _create_job(auth_client, [301])

    # Before processing: no timing yet.
    fresh = auth_client.get(f"/jobs/{job['id']}").json()
    assert fresh["started_at"] is None
    assert fresh["duration_seconds"] is None

    # Drain the single item with a trivial processor (stages nothing real).
    db = next(app.dependency_overrides[get_db]())

    def _stage(_db: object, item: EnrichmentItem) -> None:
        item.staged_title = "done"

    assert process_one(db, _stage) is True
    assert process_one(db, _stage) is False  # queue drained

    settled = auth_client.get(f"/jobs/{job['id']}").json()
    assert settled["status"] == "completed"
    assert settled["started_at"] is not None
    assert settled["finished_at"] is not None
    assert settled["duration_seconds"] is not None
    assert settled["duration_seconds"] >= 0


def test_read_item_product_returns_current_tillin_product(
    auth_client: TestClient,
) -> None:
    from app.api.deps import get_db, get_xano_client
    from app.api.schemas import Brand, Product
    from app.main import app
    from app.models import EnrichmentItem

    job = _create_job(auth_client, [555])
    db = next(app.dependency_overrides[get_db]())
    item = db.query(EnrichmentItem).filter_by(job_id=job["id"]).first()
    assert item is not None
    item_id = item.id

    class _FakeXano:
        def get_product(self, pid: int) -> Product:
            return Product(
                id=pid,
                title="Polo rayé",
                reference_code="R1",
                brand=Brand(id=1, name="ARMEDANGELS"),
                category="Polos",
                description="Description Tillin actuelle",
            )

    app.dependency_overrides[get_xano_client] = lambda: _FakeXano()
    try:
        resp = auth_client.get(f"/items/{item_id}/product")
        assert resp.status_code == 200
        body = resp.json()
        assert body["id"] == 555
        assert body["brand"]["name"] == "ARMEDANGELS"
        assert body["description"] == "Description Tillin actuelle"
    finally:
        app.dependency_overrides.pop(get_xano_client, None)


def test_resolve_item_manually_restages(auth_client: TestClient) -> None:
    from app.api.deps import get_db, get_enrichment_pipeline
    from app.main import app
    from app.models import EnrichmentItem

    job = _create_job(auth_client, [556])
    db = next(app.dependency_overrides[get_db]())
    item = db.query(EnrichmentItem).filter_by(job_id=job["id"]).first()
    assert item is not None
    item_id = item.id

    class _FakePipeline:
        def stage_from_url(self, it: EnrichmentItem, url: str) -> None:
            it.source_url = url
            it.source_method = "manual"
            it.match_score = 0.9
            it.staged_images_json = [{"url": "https://x/1.jpg", "position": 1}]

    app.dependency_overrides[get_enrichment_pipeline] = lambda: _FakePipeline()
    try:
        valid = {"source_url": "https://x/products/foo"}
        # Pending item: cannot re-resolve yet.
        assert (
            auth_client.post(f"/items/{item_id}/resolve", json=valid).status_code == 409
        )

        item.status = "ready_for_review"
        db.commit()

        # Any http(s) URL is accepted since the Firecrawl fallback (non-Shopify
        # pages are extracted); only non-URLs are rejected by the schema.
        assert (
            auth_client.post(
                f"/items/{item_id}/resolve", json={"source_url": "not-a-url"}
            ).status_code
            == 422
        )

        resp = auth_client.post(f"/items/{item_id}/resolve", json=valid)
        assert resp.status_code == 200
        body = resp.json()
        assert body["source_method"] == "manual"
        assert body["match_score"] == 0.9
        assert body["source_url"] == "https://x/products/foo"
    finally:
        app.dependency_overrides.pop(get_enrichment_pipeline, None)


def test_retry_item_resets_and_requeues(auth_client: TestClient) -> None:
    from app.api.deps import get_db, get_job_runner
    from app.main import app
    from app.models import EnrichmentItem

    job = _create_job(auth_client, [601])
    db = next(app.dependency_overrides[get_db]())
    item = db.query(EnrichmentItem).filter_by(job_id=job["id"]).first()
    assert item is not None
    item_id = item.id

    # A pending item cannot be retried.
    assert auth_client.post(f"/items/{item_id}/retry").status_code == 409

    # Stage a full result, then retry.
    item.status = "ready_for_review"
    item.staged_title = "Titre"
    item.staged_description = "Desc"
    item.source_url = "https://x/products/foo"
    item.source_method = "shopify_json"
    item.match_score = 1.0
    item.attempt_count = 1
    db.commit()

    runs: list[int] = []
    app.dependency_overrides[get_job_runner] = lambda: runs.append
    try:
        response = auth_client.post(f"/items/{item_id}/retry")
    finally:
        app.dependency_overrides[get_job_runner] = lambda: lambda job_id: None

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "pending"
    assert body["staged_title"] is None
    assert body["source_url"] is None
    assert body["attempt_count"] == 0
    assert runs == [job["id"]]

    # The parent job is re-opened.
    parent = auth_client.get(f"/jobs/{job['id']}").json()
    assert parent["status"] == "pending"
    assert parent["finished_at"] is None


def test_retry_job_requeues_failed_and_rejected(auth_client: TestClient) -> None:
    from app.api.deps import get_db
    from app.main import app
    from app.models import EnrichmentItem

    job = _create_job(auth_client, [611, 612, 613])

    # Nothing failed yet -> 409.
    assert auth_client.post(f"/jobs/{job['id']}/retry").status_code == 409

    db = next(app.dependency_overrides[get_db]())
    items = db.query(EnrichmentItem).filter_by(job_id=job["id"]).all()
    items[0].status = "failed"
    items[0].error = "boom"
    items[1].status = "rejected"
    items[2].status = "applied"
    db.commit()

    response = auth_client.post(f"/jobs/{job['id']}/retry")
    assert response.status_code == 200
    counts = response.json()["counts"]
    assert counts["pending"] == 2  # failed + rejected requeued
    assert counts["applied"] == 1  # applied untouched


def test_apply_writes_to_destination_and_marks_applied(
    auth_client: TestClient,
) -> None:
    job = _create_job(auth_client, [1911])

    from app.api.deps import get_db, get_xano_client
    from app.main import app
    from app.models import EnrichmentItem

    # Stage + find the item.
    db = next(app.dependency_overrides[get_db]())
    item = db.query(EnrichmentItem).filter_by(job_id=job["id"]).first()
    assert item is not None
    item.status = "ready_for_review"
    item.staged_title = "Nouveau titre"
    item.staged_description = "Desc"
    item.staged_images_json = [{"url": "https://a.jpg"}]
    db.commit()
    item_id = item.id

    # A capturing fake Xano client for the destination writes.
    writes: dict[str, Any] = {}

    class _FakeXano:
        def add_product_images(self, pid: int, urls: list[str]) -> None:
            writes["images"] = (pid, urls)

        def enrich_product(self, pid: int, **kw: Any) -> None:
            writes["enrich"] = (pid, kw)

    app.dependency_overrides[get_xano_client] = lambda: _FakeXano()
    try:
        # Cannot apply before approval (Xano available, but wrong state).
        assert auth_client.post(f"/items/{item_id}/apply").status_code == 409

        assert auth_client.post(f"/items/{item_id}/approve").status_code == 200

        response = auth_client.post(f"/items/{item_id}/apply")
        assert response.status_code == 200
        assert response.json()["status"] == "applied"
        assert writes["images"] == (1911, ["https://a.jpg"])
        assert writes["enrich"][0] == 1911
        assert writes["enrich"][1]["title"] == "Nouveau titre"

        # Re-applying an already-applied item is rejected.
        assert auth_client.post(f"/items/{item_id}/apply").status_code == 409
    finally:
        app.dependency_overrides.pop(get_xano_client, None)


def test_normalize_item_image_per_entry_and_revert(
    auth_client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Reviewer-chosen per-image normalization (originals staged by default):
    normalize one entry, selection follows the new url, revert restores it."""
    import httpx

    import app.imaging.service as imaging_service
    from app.api.deps import get_db, get_photoroom_client
    from app.clients.photoroom import PhotoroomClient
    from app.main import app
    from app.models import EnrichmentItem, ImageAsset, UsageEvent
    from tests.images import cutout_png, source_jpeg

    monkeypatch.setattr(imaging_service, "_download_source", lambda url: source_jpeg())

    job = _create_job(auth_client, [1911])
    db = next(app.dependency_overrides[get_db]())
    item = db.query(EnrichmentItem).filter_by(job_id=job["id"]).first()
    assert item is not None
    item.status = "ready_for_review"
    item.staged_images_json = [
        {"url": "https://cdn.x/1.jpg", "position": 1},
        {"url": "https://cdn.x/2.jpg", "position": 2},
    ]
    item.apply_fields_json = {"image_urls": ["https://cdn.x/1.jpg"]}
    db.commit()
    item_id = item.id

    photoroom = PhotoroomClient(
        "pr-key",
        transport=httpx.MockTransport(
            lambda r: httpx.Response(200, content=cutout_png())
        ),
    )
    app.dependency_overrides[get_photoroom_client] = lambda: photoroom
    try:
        # Unknown url -> 404.
        missing = auth_client.post(
            f"/items/{item_id}/images/normalize", json={"url": "https://cdn.x/9.jpg"}
        )
        assert missing.status_code == 404

        resp = auth_client.post(
            f"/items/{item_id}/images/normalize", json={"url": "https://cdn.x/1.jpg"}
        )
        assert resp.status_code == 200
        entries = resp.json()["staged_images_json"]
        assert entries[1] == {"url": "https://cdn.x/2.jpg", "position": 2}
        first = entries[0]
        assert first["source_url"] == "https://cdn.x/1.jpg"
        assert first["position"] == 1
        asset_id = first["asset_id"]
        assert first["url"] == f"/imaging/assets/{asset_id}/files/0"
        # The reviewer's partial selection follows the entry's new url.
        assert resp.json()["apply_fields_json"]["image_urls"] == [first["url"]]
        asset = db.get(ImageAsset, asset_id)
        db.refresh(asset)
        assert asset.status == "completed"
        events = db.query(UsageEvent).filter_by(item_id=item_id).all()
        assert [(e.provider, e.metric, e.quantity) for e in events] == [
            ("photoroom", "images", 1)
        ]

        # Normalizing an already-normalized entry -> 409.
        again = auth_client.post(
            f"/items/{item_id}/images/normalize", json={"url": first["url"]}
        )
        assert again.status_code == 409

        # Revert restores the original url (and the selection).
        back = auth_client.post(
            f"/items/{item_id}/images/normalize",
            json={"url": first["url"], "revert": True},
        )
        assert back.status_code == 200
        assert back.json()["staged_images_json"][0] == {
            "url": "https://cdn.x/1.jpg",
            "position": 1,
        }
        assert back.json()["apply_fields_json"]["image_urls"] == ["https://cdn.x/1.jpg"]

        # Reverting a raw entry -> 409.
        raw = auth_client.post(
            f"/items/{item_id}/images/normalize",
            json={"url": "https://cdn.x/2.jpg", "revert": True},
        )
        assert raw.status_code == 409

        # Wrong item status -> 409.
        item.status = "applied"
        db.commit()
        locked = auth_client.post(
            f"/items/{item_id}/images/normalize", json={"url": "https://cdn.x/2.jpg"}
        )
        assert locked.status_code == 409
    finally:
        app.dependency_overrides.pop(get_photoroom_client, None)


def test_failed_item_can_be_dismissed_as_rejected(auth_client: TestClient) -> None:
    # « Écarter » un échec nettoie la liste sans rien supprimer.
    job = _create_job(auth_client, [43])
    item_id = _first_item_id(auth_client, job)

    from app.api.deps import get_db
    from app.main import app
    from app.models import EnrichmentItem

    override = app.dependency_overrides[get_db]
    db = next(override())
    db_item = db.get(EnrichmentItem, item_id)
    assert db_item is not None
    db_item.status = "failed"
    db.commit()

    rejected = auth_client.post(f"/items/{item_id}/reject")
    assert rejected.status_code == 200
    assert rejected.json()["status"] == "rejected"
    # Mais un échec ne se « valide » toujours pas.
    db_item = db.get(EnrichmentItem, item_id)
    db_item.status = "failed"
    db.commit()
    assert auth_client.post(f"/items/{item_id}/approve").status_code == 409
