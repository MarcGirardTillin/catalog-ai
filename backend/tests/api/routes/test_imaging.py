"""Tests for the imaging routes: /products/{id}/images/* + /imaging/*."""

import json
from collections.abc import Callable, Iterator
from datetime import UTC, datetime
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
    verb: str = "normalize",
    staged_paths: list[str] | None = None,
    source_product_image_id: int | None = None,
    tillin_image_ids: list[int] | None = None,
    product_id: int = 101,
    account_id: int | None = None,
) -> int:
    db = _db(factory)
    try:
        if account_id is None:
            account = db.scalar(select(Account))
            if account is None:
                account = Account(name="default")
                db.add(account)
                db.commit()
            account_id = account.id
        asset = ImageAsset(
            account_id=account_id,
            product_id=product_id,
            verb=verb,
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


def _normalized_asset_id(auth_client: TestClient) -> int:
    """Run the real normalize flow (mocks installed by the caller)."""
    response = auth_client.post(
        "/products/101/images/normalize",
        json={"image_url": "https://cdn.tillin/vm01-1.jpg", "product_image_id": 501},
    )
    assert response.status_code == 202, response.text
    asset_id: int = response.json()["id"]
    assert auth_client.get(f"/imaging/assets/{asset_id}").json()["status"] == (
        "completed"
    )
    return asset_id


# ---- POST /products/{id}/images/normalize (202 + background) ----


def test_normalize_requires_authentication(client: TestClient) -> None:
    response = client.post(
        "/products/101/images/normalize", json={"image_url": "https://img/1.jpg"}
    )
    assert response.status_code == 401


@pytest.mark.usefixtures("patch_source_download")
def test_normalize_202_then_background_completes_with_metadata(
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

    # 202; the TestClient runs the BackgroundTask before returning, so the
    # asset has already settled by the time we poll it.
    assert response.status_code == 202, response.text
    asset_id = response.json()["id"]
    assert response.json()["verb"] == "normalize"

    body = auth_client.get(f"/imaging/assets/{asset_id}").json()
    assert body["status"] == "completed"
    assert body["provider"] == "photoroom"
    assert body["product_id"] == 101
    assert body["source_product_image_id"] == 501
    assert body["preview_urls"] == [f"/imaging/assets/{asset_id}/files/0"]
    assert body["finished_at"] is not None
    # Weight/dimensions metadata: output AND source; render is possible.
    assert body["files"] == [
        {
            "index": 0,
            "size_bytes": (staging_dir / str(asset_id) / "0.webp").stat().st_size,
            "width": 1600,
            "height": 2000,
            "format": "webp",
        }
    ]
    assert body["source_width"] == 800 and body["source_height"] == 1000
    assert body["source_size_bytes"] and body["can_render"] is True
    # Output, source and cutout are all staged (re-render needs them).
    staged = (staging_dir / str(asset_id) / "0.webp").read_bytes()
    assert probe(staged) == (1600, 2000, "webp")
    assert (staging_dir / str(asset_id) / "cutout.png").is_file()
    assert (staging_dir / str(asset_id) / "source.jpeg").is_file()
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

    assert response.status_code == 202  # the failure lands on the asset
    polled = auth_client.get(f"/imaging/assets/{response.json()['id']}").json()
    assert polled["status"] == "failed"
    assert polled["error"]
    assert polled["can_render"] is False
    db = _db(db_session_factory)
    try:
        # No usage row for a failed provider call.
        assert db.scalar(select(UsageEvent)) is None
    finally:
        db.close()


@pytest.mark.usefixtures("patch_source_download")
def test_normalize_uses_account_imaging_defaults(
    auth_client: TestClient,
    override_photoroom: Callable[[Handler], None],
    db_session_factory: sessionmaker[Session],
    staging_dir: Path,
) -> None:
    override_photoroom(lambda r: httpx.Response(200, content=cutout_png()))
    # The client configures its imaging defaults (regular settings PUT).
    put = auth_client.put(
        "/settings/account",
        json={
            "imaging_bg_color": "112233",
            "imaging_format": "png",
            "imaging_remove_bg": False,
        },
    )
    assert put.status_code == 200

    # No options in the request → account defaults apply (fully local here).
    response = auth_client.post(
        "/products/101/images/normalize",
        json={"image_url": "https://cdn.tillin/vm01-1.jpg"},
    )
    assert response.status_code == 202
    asset_id = response.json()["id"]
    body = auth_client.get(f"/imaging/assets/{asset_id}").json()
    assert body["status"] == "completed"
    assert body["provider"] == "local"  # remove_bg off by account default
    assert (staging_dir / str(asset_id) / "0.png").is_file()
    db = _db(db_session_factory)
    try:
        asset = db.get(ImageAsset, asset_id)
        assert asset is not None
        options = asset.params_json["options"]
        assert options["bg_color"] == "112233"
        assert options["format"] == "png"
        assert options["remove_bg"] is False
        assert db.scalar(select(UsageEvent)) is None  # fully local, unmetered
    finally:
        db.close()

    # A partial override wins field by field, the rest keeps the defaults.
    override = auth_client.post(
        "/products/101/images/normalize",
        json={
            "image_url": "https://cdn.tillin/vm01-1.jpg",
            "options": {"bg_color": "445566"},
        },
    )
    partial = auth_client.get(f"/imaging/assets/{override.json()['id']}").json()
    db = _db(db_session_factory)
    try:
        asset = db.get(ImageAsset, partial["id"])
        assert asset is not None
        assert asset.params_json["options"]["bg_color"] == "445566"
        assert asset.params_json["options"]["format"] == "png"  # default kept
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


def test_generate_model_prompt_comes_from_account_generation_settings(
    auth_client: TestClient,
    override_fashn: Callable[[Handler], None],
) -> None:
    runs: list[dict[str, Any]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/v1/run":
            runs.append(json.loads(request.content))
        return _fashn_ok_handler(request)

    override_fashn(handler)
    put = auth_client.put(
        "/settings/account",
        json={
            "imaging_generation_framing": "cropped_head",
            "imaging_generation_scene": "lifestyle",
            "imaging_generation_instructions": "urban street style",
        },
    )
    assert put.status_code == 200

    # Sans options : instruction composée depuis les réglages du compte.
    response = auth_client.post(
        "/products/101/images/generate-model",
        json={"image_url": "https://cdn.tillin/vm01-1.jpg"},
    )
    assert response.status_code == 202
    assert runs[0]["inputs"]["prompt"] == (
        "lifestyle photo, natural in-context setting, "
        "framed from the neck down, the model's head cropped out of frame, "
        "urban street style"
    )

    # Overrides ponctuels champ par champ (directives vidées explicitement).
    response = auth_client.post(
        "/products/101/images/generate-model",
        json={
            "image_url": "https://cdn.tillin/vm01-1.jpg",
            "options": {"scene": "studio", "instructions": ""},
        },
    )
    assert response.status_code == 202
    assert runs[1]["inputs"]["prompt"] == (
        "studio photo, plain light neutral background, "
        "framed from the neck down, the model's head cropped out of frame"
    )


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


# ---- POST /imaging/assets/{id}/render ----


@pytest.mark.usefixtures("patch_source_download")
def test_render_recomposes_locally_without_provider(
    auth_client: TestClient,
    override_photoroom: Callable[[Handler], None],
    db_session_factory: sessionmaker[Session],
    staging_dir: Path,
) -> None:
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request.url.path)
        return httpx.Response(200, content=cutout_png())

    override_photoroom(handler)
    asset_id = _normalized_asset_id(auth_client)
    assert calls == ["/v1/segment"]

    response = auth_client.post(
        f"/imaging/assets/{asset_id}/render",
        json={"offset_x": 200, "scale": 0.8, "bg_color": "102030", "format": "png"},
    )

    assert response.status_code == 200, response.text
    body = response.json()
    # Cache busting + new output metadata (format changed to png).
    assert body["preview_urls"] == [f"/imaging/assets/{asset_id}/files/0?r=1"]
    assert body["files"][0]["format"] == "png"
    assert probe((staging_dir / str(asset_id) / "0.png").read_bytes()) == (
        1600,
        2000,
        "png",
    )
    # NO new provider call, NO new usage event.
    assert calls == ["/v1/segment"]
    db = _db(db_session_factory)
    try:
        assert db.query(UsageEvent).count() == 1
    finally:
        db.close()

    # A second render bumps the revision again.
    again = auth_client.post(f"/imaging/assets/{asset_id}/render", json={})
    assert again.json()["preview_urls"][0].endswith("?r=2")


@pytest.mark.usefixtures("patch_source_download")
def test_render_crop_cuts_the_output_and_is_echoed(
    auth_client: TestClient,
    override_photoroom: Callable[[Handler], None],
    staging_dir: Path,
) -> None:
    """POST /render avec `crop` : la sortie prend les dimensions du cadre et
    le recadrage est réhydratable (render_crop) ; un render SANS crop repart
    de l'image entière."""
    override_photoroom(lambda r: httpx.Response(200, content=cutout_png()))
    asset_id = _normalized_asset_id(auth_client)

    response = auth_client.post(
        f"/imaging/assets/{asset_id}/render",
        json={
            "format": "png",
            "crop": {"x": 200, "y": 250, "width": 800, "height": 1000},
        },
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["files"][0]["width"] == 800
    assert body["files"][0]["height"] == 1000
    assert body["render_crop"] == {"x": 200, "y": 250, "width": 800, "height": 1000}
    assert probe((staging_dir / str(asset_id) / "0.png").read_bytes())[:2] == (
        800,
        1000,
    )

    # Recomposition sans crop : retour à l'image entière.
    full = auth_client.post(
        f"/imaging/assets/{asset_id}/render", json={"format": "png"}
    )
    assert full.status_code == 200
    assert full.json()["render_crop"] is None
    assert full.json()["files"][0]["width"] == 1600


@pytest.mark.usefixtures("patch_source_download")
def test_render_guards_409(
    auth_client: TestClient,
    override_photoroom: Callable[[Handler], None],
    db_session_factory: sessionmaker[Session],
) -> None:
    def expect(asset_id: int, code: str) -> None:
        response = auth_client.post(f"/imaging/assets/{asset_id}/render", json={})
        assert response.status_code == 409, response.text
        assert response.json()["code"] == code

    # Legacy asset (no staged cutout/source metadata) → staging_expired.
    expect(
        _make_asset(db_session_factory, staged_paths=["1/0.webp"]), "staging_expired"
    )
    expect(_make_asset(db_session_factory, status="processing"), "asset_not_completed")
    expect(
        _make_asset(db_session_factory, tillin_image_ids=[900]), "asset_already_saved"
    )
    expect(_make_asset(db_session_factory, verb="generate_model"), "unsupported_verb")

    # Cutout referenced but purged from disk → staging_expired.
    override_photoroom(lambda r: httpx.Response(200, content=cutout_png()))
    asset_id = _normalized_asset_id(auth_client)
    from app.imaging import staging as staging_module

    staging_module.purge_asset(asset_id)
    expect(asset_id, "staging_expired")


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


def test_save_with_custom_filenames_slugs_and_imposes_extension(
    auth_client: TestClient,
    override_xano: Callable[[Handler], None],
    db_session_factory: sessionmaker[Session],
) -> None:
    captured: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/bulk"):
            captured.append(request)
            return httpx.Response(200, json=_bulk_response())
        return httpx.Response(404)

    override_xano(handler)

    from app.imaging import staging as staging_module

    asset_id = _make_asset(db_session_factory)
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
        f"/imaging/assets/{asset_id}/save",
        json={"filenames": ["Photo Été #1.webp"]},
    )

    assert response.status_code == 200, response.text
    # Slugged (accents/spaces/#), the known extension deduplicated.
    assert b'filename="photo-ete-1.webp"' in captured[0].content


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


# ---- GET /imaging/assets (listing) + pending-products + discard ----


def test_list_assets_filters_pending_verb_and_product(
    auth_client: TestClient, db_session_factory: sessionmaker[Session]
) -> None:
    pending_101 = _make_asset(db_session_factory, product_id=101)
    _make_asset(db_session_factory, product_id=101, tillin_image_ids=[9])  # saved
    _make_asset(db_session_factory, product_id=101, status="failed")
    gen_202 = _make_asset(db_session_factory, product_id=202, verb="generate_model")

    body = auth_client.get("/imaging/assets", params={"pending": True}).json()
    assert {a["id"] for a in body} == {pending_101, gen_202}
    assert all(a["saved"] is False for a in body)

    body = auth_client.get(
        "/imaging/assets", params={"pending": True, "product_id": 101}
    ).json()
    assert [a["id"] for a in body] == [pending_101]

    body = auth_client.get("/imaging/assets", params={"verb": "generate_model"}).json()
    assert [a["id"] for a in body] == [gen_202]

    # Full listing exposes the saved flag for the history view.
    saved_flags = {
        a["id"]: a["saved"] for a in auth_client.get("/imaging/assets").json()
    }
    assert saved_flags[pending_101] is False
    assert sum(1 for saved in saved_flags.values() if saved) == 1


def test_list_assets_month_filter_and_validation(
    auth_client: TestClient, db_session_factory: sessionmaker[Session]
) -> None:
    asset_id = _make_asset(db_session_factory)
    month = datetime.now(UTC).strftime("%Y-%m")

    body = auth_client.get("/imaging/assets", params={"month": month}).json()
    assert [a["id"] for a in body] == [asset_id]
    assert auth_client.get("/imaging/assets", params={"month": "1999-01"}).json() == []
    response = auth_client.get("/imaging/assets", params={"month": "not-a-month"})
    assert response.status_code == 422


def test_pending_products_lists_distinct_product_ids(
    auth_client: TestClient, db_session_factory: sessionmaker[Session]
) -> None:
    _make_asset(db_session_factory, product_id=101)
    _make_asset(db_session_factory, product_id=101)  # same product, one badge
    _make_asset(db_session_factory, product_id=202, verb="generate_model")
    _make_asset(db_session_factory, product_id=303, tillin_image_ids=[1])  # saved
    _make_asset(db_session_factory, product_id=404, status="failed")

    body = auth_client.get("/imaging/assets/pending-products").json()
    assert body == {"product_ids": [101, 202]}


@pytest.mark.usefixtures("patch_source_download")
def test_discard_purges_staging_and_leaves_history(
    auth_client: TestClient,
    override_photoroom: Callable[[Handler], None],
    override_xano: Callable[[Handler], None],
    staging_dir: Path,
) -> None:
    override_photoroom(lambda r: httpx.Response(200, content=cutout_png()))
    # Xano ne doit jamais être appelé : la garde 409 arrive avant l'upload.
    override_xano(lambda r: httpx.Response(500))
    asset_id = _normalized_asset_id(auth_client)
    assert (staging_dir / str(asset_id)).exists()

    response = auth_client.post(f"/imaging/assets/{asset_id}/discard")
    assert response.status_code == 200, response.text
    assert response.json()["status"] == "discarded"
    # Staging purged, row kept, excluded from the pending views.
    assert not (staging_dir / str(asset_id)).exists()
    assert auth_client.get("/imaging/assets", params={"pending": True}).json() == []
    assert auth_client.get("/imaging/assets/pending-products").json() == {
        "product_ids": []
    }
    history = auth_client.get("/imaging/assets").json()
    assert [a["id"] for a in history] == [asset_id]
    # A discarded asset can be neither saved nor re-rendered.
    save = auth_client.post(f"/imaging/assets/{asset_id}/save", json={})
    assert (save.status_code, save.json()["code"]) == (409, "asset_not_completed")
    render = auth_client.post(
        f"/imaging/assets/{asset_id}/render",
        json={"offset_x": 0, "offset_y": 0, "scale": 1},
    )
    assert (render.status_code, render.json()["code"]) == (409, "asset_not_completed")


def test_discard_guards(
    auth_client: TestClient, db_session_factory: sessionmaker[Session]
) -> None:
    saved = _make_asset(db_session_factory, tillin_image_ids=[7])
    response = auth_client.post(f"/imaging/assets/{saved}/discard")
    assert (response.status_code, response.json()["code"]) == (
        409,
        "asset_already_saved",
    )
    running = _make_asset(db_session_factory, status="processing")
    response = auth_client.post(f"/imaging/assets/{running}/discard")
    assert (response.status_code, response.json()["code"]) == (
        409,
        "asset_not_completed",
    )
