"""Tests for the imaging business verbs (providers mocked, usage in DB)."""

from collections.abc import Generator

import httpx
import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

import app.imaging.service as imaging_service
from app.clients.base import ExternalServiceError
from app.clients.fashn import FashnClient
from app.clients.photoroom import PhotoroomClient
from app.imaging.compose import probe
from app.imaging.service import (
    FinalizeOptions,
    GenerateFlatOptions,
    GenerateModelOptions,
    GenerateVirtualModelOptions,
    NormalizeOptions,
    fashn_credits,
    finalize_image,
    generate_flat_photo,
    generate_ghost_photo,
    generate_model_photo,
    generate_virtual_model_photo,
    normalize_product_image,
)
from app.models import Account, UsageEvent
from tests.images import cutout_png, source_jpeg


@pytest.fixture
def db(db_session_factory: sessionmaker[Session]) -> Generator[Session]:
    session = db_session_factory()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture
def account_id(db: Session) -> int:
    account = Account(name="default")
    db.add(account)
    db.commit()
    return account.id


def _usage_events(db: Session) -> list[UsageEvent]:
    return list(db.execute(select(UsageEvent)).scalars())


def _segment_photoroom(captured: dict[str, httpx.Request]) -> PhotoroomClient:
    def handler(request: httpx.Request) -> httpx.Response:
        captured["request"] = request
        return httpx.Response(200, content=cutout_png())

    return PhotoroomClient("pr-key", transport=httpx.MockTransport(handler))


def test_normalize_segments_composes_and_meters_one_image(
    db: Session, account_id: int
) -> None:
    captured: dict[str, httpx.Request] = {}
    outcome = normalize_product_image(
        source_jpeg(),
        options=NormalizeOptions(bg_color="F5F5F5", fmt="png"),
        photoroom=_segment_photoroom(captured),
        db=db,
        account_id=account_id,
    )
    db.commit()

    result = outcome.output
    # Dims are real now (Pillow) and follow the 4:5 default canvas.
    assert (result.width, result.height) == (1600, 2000)
    assert result.format == "png"
    assert probe(result.data) == (1600, 2000, "png")
    assert result.trace["provider"] == "photoroom"
    assert result.trace["steps"] == ["remove_bg", "compose"]
    assert result.trace["params"]["bg_color"] == "F5F5F5"
    # The cutout is kept for re-renders; the source was probed.
    assert outcome.cutout is not None
    assert (outcome.source.width, outcome.source.height) == (800, 1000)
    assert outcome.source.format == "jpeg"
    # Confirmed live: segment is a multipart POST on the sdk host.
    request = captured["request"]
    assert request.method == "POST"
    assert request.url.host == "sdk.photoroom.com"
    assert request.url.path == "/v1/segment"

    events = _usage_events(db)
    assert [(e.provider, e.metric, e.quantity, e.source) for e in events] == [
        ("photoroom", "images", 1, "imaging")
    ]
    assert events[0].model == "photoroom-segment-v1"
    assert events[0].account_id == account_id


def test_normalize_without_remove_bg_is_fully_local(
    db: Session, account_id: int
) -> None:
    def refuse(_request: httpx.Request) -> httpx.Response:
        raise AssertionError("Photoroom must not be called with remove_bg=False")

    photoroom = PhotoroomClient("pr-key", transport=httpx.MockTransport(refuse))
    outcome = normalize_product_image(
        source_jpeg(),
        options=NormalizeOptions(remove_bg=False),
        photoroom=photoroom,
        db=db,
        account_id=account_id,
    )
    db.commit()

    assert outcome.cutout is None
    assert outcome.output.trace["provider"] == "local"
    assert outcome.output.trace["steps"] == ["compose"]
    assert _usage_events(db) == []  # no provider call, nothing metered


def test_normalize_downloads_url_sources(
    db: Session, account_id: int, monkeypatch: pytest.MonkeyPatch
) -> None:
    downloaded: list[str] = []

    def fake_download(url: str) -> bytes:
        downloaded.append(url)
        return source_jpeg()

    monkeypatch.setattr(imaging_service, "_download_source", fake_download)
    outcome = normalize_product_image(
        "https://cdn.tillin/vm01-1.jpg",
        options=NormalizeOptions(remove_bg=False),
        photoroom=PhotoroomClient(
            "pr-key", transport=httpx.MockTransport(lambda r: httpx.Response(500))
        ),
        db=db,
        account_id=account_id,
    )
    assert downloaded == ["https://cdn.tillin/vm01-1.jpg"]
    assert outcome.source.format == "jpeg"


def test_normalize_rejects_unreadable_sources(db: Session, account_id: int) -> None:
    photoroom = PhotoroomClient(
        "pr-key", transport=httpx.MockTransport(lambda r: httpx.Response(200))
    )
    with pytest.raises(ExternalServiceError) as excinfo:
        normalize_product_image(
            b"not-an-image", photoroom=photoroom, db=db, account_id=account_id
        )
    assert excinfo.value.status_code == 422


def _fashn_transport(outputs: list[str]) -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/v1/run":
            return httpx.Response(200, json={"id": "pred-1", "status": "starting"})
        if request.url.path == "/v1/status/pred-1":
            return httpx.Response(
                200, json={"id": "pred-1", "status": "completed", "output": outputs}
            )
        return httpx.Response(200, content=f"img:{request.url.path}".encode())

    return httpx.MockTransport(handler)


def test_generate_model_downloads_outputs_and_meters_credits(
    db: Session, account_id: int
) -> None:
    fashn = FashnClient(
        "fx-key",
        transport=_fashn_transport(
            ["https://cdn.fashn.ai/a.jpg", "https://cdn.fashn.ai/b.jpg"]
        ),
    )
    results = generate_model_photo(
        "https://cdn.tillin/vm01-1.jpg",
        options=GenerateModelOptions(
            resolution="2k", generation_mode="quality", num_images=2
        ),
        fashn=fashn,
        db=db,
        account_id=account_id,
    )
    db.commit()

    assert [r.data for r in results] == [b"img:/a.jpg", b"img:/b.jpg"]
    assert all(r.format == "jpeg" for r in results)
    trace = results[0].trace
    assert trace["provider"] == "fashn"
    assert trace["model"] == "product-to-model"
    assert trace["seed"] == 42
    assert trace["params"]["resolution"] == "2k"

    events = _usage_events(db)
    # 2k x quality = 4 credits per image, x2 images.
    assert [(e.provider, e.metric, e.quantity, e.model) for e in events] == [
        ("fashn", "credits", 8, "product-to-model")
    ]


@pytest.mark.parametrize(
    ("resolution", "mode", "num_images", "expected"),
    [
        ("1k", "fast", 1, 1),
        ("1k", "balanced", 1, 2),
        ("1k", "quality", 1, 3),
        ("2k", "fast", 1, 2),
        ("2k", "balanced", 3, 9),
        ("4k", "fast", 1, 3),
        ("4k", "balanced", 1, 4),
        ("4k", "quality", 4, 20),
    ],
)
def test_fashn_credits_grid(
    resolution: str, mode: str, num_images: int, expected: int
) -> None:
    assert fashn_credits(resolution, mode, num_images) == expected


def test_fashn_credits_unknown_combo_raises() -> None:
    with pytest.raises(ValueError):
        fashn_credits("8k", "balanced", 1)


def test_build_generation_prompt_composes_scene_framing_and_directives() -> None:
    from app.imaging.service import build_generation_prompt

    assert build_generation_prompt("full_body", "studio", None) == (
        "studio photo, plain light neutral background, "
        "full body shot, the model fully visible"
    )
    assert build_generation_prompt("cropped_head", "lifestyle", "  denim vibe ") == (
        "lifestyle photo, natural in-context setting, "
        "framed from the neck down, the model's head cropped out of frame, "
        "denim vibe"
    )
    # Unknown values fall back to the historical default.
    assert build_generation_prompt("??", "??", None).startswith(
        "studio photo, plain light neutral background"
    )


def test_build_generation_prompt_optional_pose() -> None:
    from app.imaging.service import build_generation_prompt

    # Pose fournie : insérée entre le cadrage et les directives libres.
    assert build_generation_prompt(
        "full_body", "studio", "hands in pockets", "back"
    ) == (
        "studio photo, plain light neutral background, "
        "full body shot, the model fully visible, "
        "the model seen from behind, hands in pockets"
    )
    # Pose absente ou inconnue : rien d'ajouté (orientation libre, défaut).
    baseline = build_generation_prompt("full_body", "studio", None)
    assert build_generation_prompt("full_body", "studio", None, None) == baseline
    assert build_generation_prompt("full_body", "studio", None, "??") == baseline


def _edit_photoroom(captured: dict[str, httpx.Request]) -> PhotoroomClient:
    """MockTransport /v2/edit : capture la requête, renvoie un JPEG valide."""

    def handler(request: httpx.Request) -> httpx.Response:
        captured["request"] = request
        return httpx.Response(200, content=source_jpeg())

    return PhotoroomClient(
        "pr-key", edit_api_key="sandbox_pr-edit", transport=httpx.MockTransport(handler)
    )


def test_generate_flat_photo_calls_edit_and_meters(
    db: Session, account_id: int
) -> None:
    captured: dict[str, httpx.Request] = {}
    results = generate_flat_photo(
        "https://cdn.tillin/vm01-1.jpg",
        options=GenerateFlatOptions(prompt="  fond lin clair ", ratio="1:1"),
        photoroom=_edit_photoroom(captured),
        db=db,
        account_id=account_id,
    )
    db.commit()

    request = captured["request"]
    # GET query params aplatis en notation pointée (entrée = URL publique).
    assert request.method == "GET"
    assert request.url.host == "image-api.photoroom.com"
    assert request.url.path == "/v2/edit"
    assert request.url.params["flatLay.mode"] == "ai.auto"
    assert request.url.params["flatLay.prompt"] == "fond lin clair"
    assert request.url.params["flatLay.size"] == "SQUARE_HD"
    assert request.url.params["imageUrl"] == "https://cdn.tillin/vm01-1.jpg"
    # La clé edit (sandbox de test) prime sur la clé segment pour /v2/edit.
    assert request.headers["x-api-key"] == "sandbox_pr-edit"

    assert len(results) == 1
    assert results[0].trace["model"] == "photoroom-edit-v2"
    assert results[0].trace["params"]["verb"] == "flat_lay"
    events = _usage_events(db)
    assert [(e.provider, e.metric, e.quantity, e.model) for e in events] == [
        ("photoroom", "images", 1, "photoroom-edit-v2")
    ]


def test_generate_ghost_photo_uses_ghost_mannequin_namespace(
    db: Session, account_id: int
) -> None:
    captured: dict[str, httpx.Request] = {}
    generate_ghost_photo(
        "https://cdn.tillin/vm01-1.jpg",
        options=GenerateFlatOptions(),
        photoroom=_edit_photoroom(captured),
        db=db,
        account_id=account_id,
    )
    params = captured["request"].url.params
    assert params["ghostMannequin.mode"] == "ai.auto"
    assert "ghostMannequin.prompt" not in params  # prompt absent = omis


def test_generate_virtual_model_photo_maps_presets_and_views(
    db: Session, account_id: int
) -> None:
    captured: dict[str, httpx.Request] = {}
    generate_virtual_model_photo(
        "https://cdn.tillin/vm01-1.jpg",
        options=GenerateVirtualModelOptions(
            prompt="street style",
            model_preset="avery",
            scene_preset="studio",
            pose="34turn",
            additional_image_urls=[
                "https://cdn.tillin/vm01-2.jpg",
                "https://cdn.tillin/vm01-3.jpg",
            ],
        ),
        photoroom=_edit_photoroom(captured),
        db=db,
        account_id=account_id,
    )
    params = captured["request"].url.params
    assert params["virtualModel.mode"] == "ai.auto"
    assert params["virtualModel.model.preset.name"] == "avery"
    assert params["virtualModel.scene.preset.name"] == "studio"
    assert params["virtualModel.pose"] == "34turn"
    assert params["virtualModel.prompt"] == "street style"
    assert (
        params["virtualModel.additionalProductImages[0].imageUrl"]
        == "https://cdn.tillin/vm01-2.jpg"
    )
    assert (
        params["virtualModel.additionalProductImages[1].imageUrl"]
        == "https://cdn.tillin/vm01-3.jpg"
    )


def test_generate_virtual_model_photo_skips_unknown_pose(
    db: Session, account_id: int
) -> None:
    captured: dict[str, httpx.Request] = {}
    generate_virtual_model_photo(
        "https://cdn.tillin/vm01-1.jpg",
        options=GenerateVirtualModelOptions(pose="not-a-pose"),
        photoroom=_edit_photoroom(captured),
        db=db,
        account_id=account_id,
    )
    assert "virtualModel.pose" not in captured["request"].url.params


def test_finalize_image_combines_options_in_one_multipart_call(
    db: Session, account_id: int
) -> None:
    captured: dict[str, httpx.Request] = {}
    result = finalize_image(
        cutout_png(),
        options=FinalizeOptions(
            shadow_mode="soft",
            background_color="#F5F5F5",
            ironing=True,
            upscale=True,
            beautify=True,
            recolor_prompt="bordeaux",
            output_format="webp",
        ),
        photoroom=_edit_photoroom(captured),
        db=db,
        account_id=account_id,
    )
    db.commit()

    request = captured["request"]
    # Entrée en bytes (staging non public) -> POST multipart imageFile.
    assert request.method == "POST"
    assert request.url.path == "/v2/edit"
    body = request.read()
    assert b"imageFile" in body
    assert b'name="shadow.mode"' in body and b"ai.soft" in body
    # Pas d'overrides d'ombre : rejetés (400) hors modèles avancés.
    assert b"intensityOverride" not in body
    assert b'name="background.color"' in body and b"F5F5F5" in body
    assert b'name="ironing.mode"' in body
    assert b'name="upscale.mode"' in body and b"ai.fast" in body
    assert b'name="beautify.mode"' in body
    assert b'name="editWithAI.prompt"' in body and b"bordeaux" in body
    assert b'name="export.format"' in body and b"webp" in body

    assert result.trace["params"]["verb"] == "finalize"
    events = _usage_events(db)
    assert [(e.provider, e.metric, e.quantity, e.model) for e in events] == [
        ("photoroom", "images", 1, "photoroom-edit-v2")
    ]


def test_finalize_image_background_prompt_wins_over_color(
    db: Session, account_id: int
) -> None:
    captured: dict[str, httpx.Request] = {}
    finalize_image(
        cutout_png(),
        options=FinalizeOptions(
            background_color="FFFFFF", background_prompt="marble table, soft light"
        ),
        photoroom=_edit_photoroom(captured),
        db=db,
        account_id=account_id,
    )
    body = captured["request"].read()
    assert b'name="background.prompt"' in body
    assert b'name="background.color"' not in body


def test_finalize_image_requires_an_active_option(db: Session, account_id: int) -> None:
    with pytest.raises(ValueError):
        finalize_image(
            cutout_png(),
            options=FinalizeOptions(),
            photoroom=_edit_photoroom({}),
            db=db,
            account_id=account_id,
        )
    assert _usage_events(db) == []
