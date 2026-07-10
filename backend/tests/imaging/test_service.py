"""Tests for the imaging business verbs (providers mocked, usage in DB)."""

from collections.abc import Generator

import httpx
import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app.clients.fashn import FashnClient
from app.clients.photoroom import PhotoroomClient
from app.imaging.service import (
    GenerateModelOptions,
    NormalizeOptions,
    fashn_credits,
    generate_flat_photo,
    generate_model_photo,
    normalize_product_image,
)
from app.models import Account, UsageEvent


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


def test_normalize_calls_photoroom_and_meters_one_image(
    db: Session, account_id: int
) -> None:
    captured: dict[str, httpx.Request] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["request"] = request
        return httpx.Response(200, content=b"processed-webp")

    photoroom = PhotoroomClient("pr-key", transport=httpx.MockTransport(handler))
    result = normalize_product_image(
        "https://cdn.tillin/vm01-1.jpg",
        options=NormalizeOptions(bg_color="F5F5F5", quality=90),
        photoroom=photoroom,
        db=db,
        account_id=account_id,
    )
    db.commit()

    assert result.data == b"processed-webp"
    assert result.format == "webp"
    assert result.width is None and result.height is None  # no Pillow in deps
    assert result.trace["provider"] == "photoroom"
    assert result.trace["params"]["bg_color"] == "F5F5F5"
    # Confirmed live: Photoroom /v2/edit reads its params from the GET query.
    assert captured["request"].method == "GET"
    assert captured["request"].url.params["background.color"] == "F5F5F5"
    assert captured["request"].url.params["export.quality"] == "90"

    events = _usage_events(db)
    assert [(e.provider, e.metric, e.quantity, e.source) for e in events] == [
        ("photoroom", "images", 1, "imaging")
    ]
    assert events[0].model == "photoroom-v2"
    assert events[0].account_id == account_id


def test_normalize_rejects_raw_bytes_for_now(db: Session, account_id: int) -> None:
    photoroom = PhotoroomClient(
        "pr-key", transport=httpx.MockTransport(lambda r: httpx.Response(200))
    )
    with pytest.raises(NotImplementedError):
        normalize_product_image(
            b"raw-bytes", photoroom=photoroom, db=db, account_id=account_id
        )


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


def test_generate_flat_photo_is_reserved() -> None:
    with pytest.raises(NotImplementedError):
        generate_flat_photo()
