"""Tests for the imaging routes: /products/{id}/images/* + /imaging/*."""

import json
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

import app.api.services.imaging as imaging_services
import app.imaging.service as imaging_service
from app.api.deps import get_fashn_client, get_photoroom_client, get_xano_client
from app.clients.fashn import FashnClient
from app.clients.photoroom import PhotoroomClient
from app.clients.xano import XanoClient
from app.core.config import settings
from app.imaging.compose import probe
from app.main import app
from app.models import Account, ImageAsset, UsageEvent
from tests.images import cutout_png, source_jpeg

Handler = Callable[[httpx.Request], httpx.Response]


@pytest.fixture(autouse=True)
def staging_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    directory = tmp_path / "imaging"
    monkeypatch.setattr(settings, "IMAGING_DIR", str(directory))
    return directory


@pytest.fixture(autouse=True)
def _background_sessions(
    db_session_factory: sessionmaker[Session], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Point the background task's own sessions at the test database."""
    monkeypatch.setattr(imaging_services, "SessionLocal", db_session_factory)


@pytest.fixture
def patch_source_download(monkeypatch: pytest.MonkeyPatch) -> None:
    """The verb downloads the source itself: keep the tests off the network."""
    monkeypatch.setattr(imaging_service, "_download_source", lambda url: source_jpeg())


@pytest.fixture
def override_photoroom() -> Iterator[Callable[[Handler], None]]:
    def install(handler: Handler) -> None:
        app.dependency_overrides[get_photoroom_client] = lambda: PhotoroomClient(
            "pr-key", transport=httpx.MockTransport(handler)
        )

    yield install
    app.dependency_overrides.pop(get_photoroom_client, None)


@pytest.fixture
def override_fashn() -> Iterator[Callable[[Handler], None]]:
    def install(handler: Handler) -> None:
        app.dependency_overrides[get_fashn_client] = lambda: FashnClient(
            "fx-key", transport=httpx.MockTransport(handler)
        )

    yield install
    app.dependency_overrides.pop(get_fashn_client, None)


@pytest.fixture
def override_xano() -> Iterator[Callable[[Handler], None]]:
    def install(handler: Handler) -> None:
        def with_login(request: httpx.Request) -> httpx.Response:
            if request.url.path.endswith("/auth/login"):
                return httpx.Response(200, json={"authToken": "jwt-token"})
            return handler(request)

        app.dependency_overrides[get_xano_client] = lambda: XanoClient(
            "https://tillin.test",
            email="svc@tillin.fr",
            password="secret",
            transport=httpx.MockTransport(with_login),
        )

    yield install
    app.dependency_overrides.pop(get_xano_client, None)


def _db(factory: sessionmaker[Session]) -> Session:
    return factory()


def _make_asset(
    factory: sessionmaker[Session],
    *,
    status: str = "completed",
    staged_paths: list[str] | None = None,
    source_product_image_id: int | None = None,
    tillin_image_ids: list[int] | None = None,
) -> int:
    db = _db(factory)
    try:
        account = db.scalar(select(Account))
        if account is None:
            account = Account(name="default")
            db.add(account)
            db.commit()
        asset = ImageAsset(
            account_id=account.id,
            product_id=101,
            verb="normalize",
            provider="photoroom",
            status=status,
            staged_paths_json=staged_paths or [],
            source_product_image_id=source_product_image_id,
            tillin_image_ids_json=tillin_image_ids,
        )
        db.add(asset)
        db.commit()
        return asset.id
    finally:
        db.close()


# ---- POST /products/{id}/images/normalize (sync) ----


def test_normalize_requires_authentication(client: TestClient) -> None:
    response = client.post(
        "/products/101/images/normalize", json={"image_url": "https://img/1.jpg"}
    )
    assert response.status_code == 401


@pytest.mark.usefixtures("patch_source_download")
def test_normalize_creates_completed_asset_with_preview(
    auth_client: TestClient,
    override_photoroom: Callable[[Handler], None],
    db_session_factory: sessionmaker[Session],
    staging_dir: Path,
) -> None:
    override_photoroom(lambda r: httpx.Response(200, content=cutout_png()))

    response = auth_client.post(
        "/products/101/images/normalize",
        json={
            "image_url": "https://cdn.tillin/vm01-1.jpg",
            "product_image_id": 501,
            "options": {"bg_color": "F5F5F5"},
        },
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["status"] == "completed"
    assert body["verb"] == "normalize"
    assert body["provider"] == "photoroom"
    assert body["product_id"] == 101
    assert body["source_product_image_id"] == 501
    assert body["preview_urls"] == [f"/imaging/assets/{body['id']}/files/0"]
    assert body["finished_at"] is not None
    # The composed output is staged on disk (real 4:5 webp) and metered.
    staged = (staging_dir / str(body["id"]) / "0.webp").read_bytes()
    assert probe(staged) == (1600, 2000, "webp")
    db = _db(db_session_factory)
    try:
        events = list(db.execute(select(UsageEvent)).scalars())
        assert [(e.provider, e.metric, e.quantity) for e in events] == [
            ("photoroom", "images", 1)
        ]
        assert events[0].model == "photoroom-segment-v1"
    finally:
        db.close()


@pytest.mark.usefixtures("patch_source_download")
def test_normalize_provider_error_marks_asset_failed(
    auth_client: TestClient,
    override_photoroom: Callable[[Handler], None],
    db_session_factory: sessionmaker[Session],
) -> None:
    override_photoroom(lambda r: httpx.Response(402))

    response = auth_client.post(
        "/products/101/images/normalize",
        json={"image_url": "https://cdn.tillin/vm01-1.jpg"},
    )

    assert response.status_code == 502
    assert response.json()["code"] == "photoroom_error"
    db = _db(db_session_factory)
    try:
        asset = db.scalar(select(ImageAsset))
        assert asset is not None
        assert asset.status == "failed"
        assert asset.error
        # No usage row for a failed provider call.
        assert db.scalar(select(UsageEvent)) is None
    finally:
        db.close()


# ---- POST /products/{id}/images/generate-model (202 + background) ----


def _fashn_ok_handler(request: httpx.Request) -> httpx.Response:
    if request.url.path == "/v1/run":
        return httpx.Response(200, json={"id": "pred-1", "status": "starting"})
    if request.url.path.startswith("/v1/status/"):
        return httpx.Response(
            200,
            json={
                "id": "pred-1",
                "status": "completed",
                "output": ["https://cdn.fashn.ai/a.jpg"],
            },
        )
    return httpx.Response(200, content=b"generated-jpeg")


def test_generate_model_202_then_background_completes(
    auth_client: TestClient,
    override_fashn: Callable[[Handler], None],
    db_session_factory: sessionmaker[Session],
) -> None:
    override_fashn(_fashn_ok_handler)

    response = auth_client.post(
        "/products/101/images/generate-model",
        json={
            "image_url": "https://cdn.tillin/vm01-1.jpg",
            "options": {"num_images": 1, "seed": 7},
        },
    )

    # 202 with the asset id; the TestClient runs the BackgroundTask before
    # returning, so the asset has already settled by the time we poll it.
    assert response.status_code == 202, response.text
    asset_id = response.json()["id"]
    assert response.json()["verb"] == "generate_model"
    assert response.json()["seed"] == 7

    polled = auth_client.get(f"/imaging/assets/{asset_id}")
    assert polled.status_code == 200
    body = polled.json()
    assert body["status"] == "completed"
    assert body["preview_urls"] == [f"/imaging/assets/{asset_id}/files/0"]

    preview = auth_client.get(f"/imaging/assets/{asset_id}/files/0")
    assert preview.status_code == 200
    assert preview.content == b"generated-jpeg"
    assert preview.headers["content-type"] == "image/jpeg"

    db = _db(db_session_factory)
    try:
        events = list(db.execute(select(UsageEvent)).scalars())
        # 1k x balanced = 2 credits x 1 image.
        assert [(e.provider, e.metric, e.quantity) for e in events] == [
            ("fashn", "credits", 2)
        ]
    finally:
        db.close()


def test_generate_model_failure_marks_asset_failed(
    auth_client: TestClient,
    override_fashn: Callable[[Handler], None],
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/v1/run":
            return httpx.Response(200, json={"id": "pred-1"})
        return httpx.Response(
            200, json={"id": "pred-1", "status": "failed", "error": "boom"}
        )

    override_fashn(handler)

    response = auth_client.post(
        "/products/101/images/generate-model",
        json={"image_url": "https://cdn.tillin/vm01-1.jpg"},
    )
    assert response.status_code == 202

    polled = auth_client.get(f"/imaging/assets/{response.json()['id']}")
    body = polled.json()
    assert body["status"] == "failed"
    assert body["error"]
    assert body["preview_urls"] == []


def test_generate_model_503_without_key_creates_no_asset(
    auth_client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
    db_session_factory: sessionmaker[Session],
) -> None:
    from app.api import deps

    monkeypatch.setattr(deps, "_fashn_client", None)
    monkeypatch.setattr(settings, "FASHN_API_KEY", "")

    response = auth_client.post(
        "/products/101/images/generate-model",
        json={"image_url": "https://cdn.tillin/vm01-1.jpg"},
    )

    assert response.status_code == 503
    assert response.json()["code"] == "fashn_not_configured"
    db = _db(db_session_factory)
    try:
        assert db.scalar(select(ImageAsset)) is None  # no zombie asset
    finally:
        db.close()


def test_generate_model_rejects_out_of_range_num_images(
    auth_client: TestClient, override_fashn: Callable[[Handler], None]
) -> None:
    override_fashn(_fashn_ok_handler)
    response = auth_client.post(
        "/products/101/images/generate-model",
        json={"image_url": "https://img/1.jpg", "options": {"num_images": 5}},
    )
    assert response.status_code == 422


# ---- GET /imaging/assets/{id} + files ----


def test_read_asset_requires_authentication(client: TestClient) -> None:
    assert client.get("/imaging/assets/1").status_code == 401


def test_read_asset_404_when_absent(auth_client: TestClient) -> None:
    response = auth_client.get("/imaging/assets/999")
    assert response.status_code == 404
    assert response.json()["code"] == "not_found"


def test_read_file_404_on_bad_index_and_missing_file(
    auth_client: TestClient, db_session_factory: sessionmaker[Session]
) -> None:
    asset_id = _make_asset(db_session_factory, staged_paths=[f"{1}/0.webp"])

    # Index out of range.
    assert auth_client.get(f"/imaging/assets/{asset_id}/files/5").status_code == 404
    # Path present in DB but file already gone from disk.
    assert auth_client.get(f"/imaging/assets/{asset_id}/files/0").status_code == 404


def test_read_file_rejects_path_traversal(
    auth_client: TestClient,
    db_session_factory: sessionmaker[Session],
    tmp_path: Path,
) -> None:
    (tmp_path / "secret.txt").write_bytes(b"secret")
    asset_id = _make_asset(db_session_factory, staged_paths=["../secret.txt"])

    response = auth_client.get(f"/imaging/assets/{asset_id}/files/0")

    assert response.status_code == 404  # traversal is refused, never served


# ---- POST /imaging/assets/{id}/save ----


def _bulk_response() -> dict[str, Any]:
    return {
        "images": [
            {"id": 900, "src": "https://xano.test/new-a.webp", "position": 4},
        ]
    }


def test_save_uploads_staged_files_and_purges(
    auth_client: TestClient,
    override_xano: Callable[[Handler], None],
    db_session_factory: sessionmaker[Session],
    staging_dir: Path,
) -> None:
    captured: dict[str, list[httpx.Request]] = {"bulk": [], "deactivate": []}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/bulk"):
            captured["bulk"].append(request)
            return httpx.Response(200, json=_bulk_response())
        if request.url.path.endswith("/product_image/deactivate"):
            captured["deactivate"].append(request)
            return httpx.Response(200, json={"ok": True})
        return httpx.Response(404)

    override_xano(handler)

    from app.imaging import staging as staging_module

    asset_id = _make_asset(db_session_factory, source_product_image_id=501)
    relpath = staging_module.store(asset_id, 0, b"processed", "webp")
    db = _db(db_session_factory)
    try:
        asset = db.get(ImageAsset, asset_id)
        assert asset is not None
        asset.staged_paths_json = [relpath]
        db.commit()
    finally:
        db.close()

    response = auth_client.post(f"/imaging/assets/{asset_id}/save", json={})

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["created"] == 1
    assert body["deactivated"] == 0  # replace not requested
    assert body["images"][0]["id"] == 900
    assert body["images"][0]["url"] == "https://xano.test/new-a.webp"
    # Multipart upload with the conventional filename, then staging purged.
    bulk = captured["bulk"][0]
    assert bulk.url.path.endswith("/product_image/101/bulk")
    assert f"normalize_{asset_id}_0.webp".encode() in bulk.content
    assert not captured["deactivate"]
    assert not (staging_dir / str(asset_id)).exists()
    db = _db(db_session_factory)
    try:
        asset = db.get(ImageAsset, asset_id)
        assert asset is not None
        assert asset.tillin_image_ids_json == [900]
    finally:
        db.close()

    # Saving twice is a 409 (the ids are already recorded).
    again = auth_client.post(f"/imaging/assets/{asset_id}/save", json={})
    assert again.status_code == 409
    assert again.json()["code"] == "asset_already_saved"


def test_save_with_replace_deactivates_the_original(
    auth_client: TestClient,
    override_xano: Callable[[Handler], None],
    db_session_factory: sessionmaker[Session],
) -> None:
    captured: dict[str, httpx.Request] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/bulk"):
            return httpx.Response(200, json=_bulk_response())
        if request.url.path.endswith("/product_image/deactivate"):
            captured["deactivate"] = request
            return httpx.Response(200, json={"ok": True})
        return httpx.Response(404)

    override_xano(handler)

    from app.imaging import staging as staging_module

    asset_id = _make_asset(db_session_factory, source_product_image_id=501)
    relpath = staging_module.store(asset_id, 0, b"processed", "webp")
    db = _db(db_session_factory)
    try:
        asset = db.get(ImageAsset, asset_id)
        assert asset is not None
        asset.staged_paths_json = [relpath]
        db.commit()
    finally:
        db.close()

    response = auth_client.post(
        f"/imaging/assets/{asset_id}/save", json={"replace": True}
    )

    assert response.status_code == 200, response.text
    assert response.json()["deactivated"] == 1
    request = captured["deactivate"]
    assert request.method == "PUT"
    assert json.loads(request.content) == {"product_image_ids": [501]}


def test_save_409_when_not_completed(
    auth_client: TestClient,
    override_xano: Callable[[Handler], None],
    db_session_factory: sessionmaker[Session],
) -> None:
    override_xano(lambda r: httpx.Response(404))
    asset_id = _make_asset(db_session_factory, status="processing")

    response = auth_client.post(f"/imaging/assets/{asset_id}/save", json={})

    assert response.status_code == 409
    assert response.json()["code"] == "asset_not_completed"
