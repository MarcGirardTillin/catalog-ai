"""Unit test for the Tillin destination adapter (staged fields -> writes)."""

from pathlib import Path
from typing import Any

import pytest
from sqlalchemy.orm import Session, sessionmaker

from app.api.exceptions import AppException
from app.api.schemas import ProductImage
from app.clients.xano import FilePart
from app.core.config import settings
from app.destinations.xano_tillin import XanoTillinDestination, _selected_weights
from app.imaging import staging
from app.models import Account, EnrichmentItem, EnrichmentJob, ImageAsset


class _FakeXano:
    def __init__(self) -> None:
        self.images: tuple[int, list[str]] | None = None
        self.uploads: tuple[int, list[FilePart]] | None = None
        self.enrich: dict[str, Any] | None = None
        self.weight: tuple[list[int], float, str] | None = None

    def add_product_images(self, product_id: int, image_urls: list[str]) -> None:
        self.images = (product_id, image_urls)

    def upload_product_images(
        self, product_id: int, files: list[FilePart]
    ) -> list[ProductImage]:
        self.uploads = (product_id, files)
        return [
            ProductImage(id=9000 + index, url=f"https://xano.example/{index}.webp")
            for index in range(len(files))
        ]

    def enrich_product(self, product_id: int, **kwargs: Any) -> None:
        self.enrich = {"product_id": product_id, **kwargs}

    def set_product_weight(
        self, product_ids: list[int], weight: float, weight_unit: str = "1"
    ) -> None:
        self.weight = (product_ids, weight, weight_unit)


def test_apply_pushes_images_then_copy() -> None:
    item = EnrichmentItem(
        job_id=1,
        account_id=1,
        tillin_product_id=1911,
        status="approved",
        staged_title="Titre",
        staged_description="Desc",
        staged_meta="Meta",
        staged_images_json=[{"url": "https://a.jpg"}, {"url": "https://b.jpg"}],
    )
    fake = _FakeXano()
    XanoTillinDestination(fake).apply(item)  # type: ignore[arg-type]

    assert fake.images == (1911, ["https://a.jpg", "https://b.jpg"])
    assert fake.enrich == {
        "product_id": 1911,
        "title": "Titre",
        "description": "Desc",
        "meta_description": "Meta",
    }


def test_apply_respects_field_selection() -> None:
    """Unchecked fields (apply_fields_json[key] == False) are not written."""
    item = EnrichmentItem(
        job_id=1,
        account_id=1,
        tillin_product_id=1911,
        status="approved",
        staged_title="Titre",
        staged_description="Desc",
        staged_meta="Meta",
        staged_images_json=[{"url": "https://a.jpg"}],
        apply_fields_json={"title": False, "images": False},
    )
    fake = _FakeXano()
    XanoTillinDestination(fake).apply(item)  # type: ignore[arg-type]

    assert fake.images is None  # images dropped
    assert fake.enrich == {
        "product_id": 1911,
        "title": None,  # dropped
        "description": "Desc",
        "meta_description": "Meta",
    }


def test_apply_with_everything_excluded_writes_nothing() -> None:
    item = EnrichmentItem(
        job_id=1,
        account_id=1,
        tillin_product_id=1911,
        status="approved",
        staged_title="Titre",
        staged_description="Desc",
        staged_meta="Meta",
        staged_images_json=[{"url": "https://a.jpg"}],
        apply_fields_json={
            "title": False,
            "description": False,
            "meta": False,
            "images": False,
        },
    )
    fake = _FakeXano()
    XanoTillinDestination(fake).apply(item)  # type: ignore[arg-type]

    assert fake.images is None
    assert fake.enrich is None


def _item_with_images(apply_fields: dict[str, Any] | None) -> EnrichmentItem:
    return EnrichmentItem(
        job_id=1,
        account_id=1,
        tillin_product_id=1911,
        status="approved",
        staged_images_json=[
            {"url": "https://a.jpg"},
            {"url": "https://b.jpg"},
            {"url": "https://c.jpg"},
        ],
        apply_fields_json=apply_fields,
    )


def test_apply_image_urls_subset_keeps_staged_order() -> None:
    # Selection order is irrelevant: staged order wins.
    item = _item_with_images({"image_urls": ["https://c.jpg", "https://a.jpg"]})
    fake = _FakeXano()
    XanoTillinDestination(fake).apply(item)  # type: ignore[arg-type]

    assert fake.images == (1911, ["https://a.jpg", "https://c.jpg"])


def test_apply_image_urls_ignores_unknown_urls() -> None:
    item = _item_with_images({"image_urls": ["https://b.jpg", "https://zzz.jpg"]})
    fake = _FakeXano()
    XanoTillinDestination(fake).apply(item)  # type: ignore[arg-type]

    assert fake.images == (1911, ["https://b.jpg"])


def test_apply_image_urls_empty_list_sends_nothing() -> None:
    item = _item_with_images({"image_urls": []})
    fake = _FakeXano()
    XanoTillinDestination(fake).apply(item)  # type: ignore[arg-type]

    assert fake.images is None


def test_apply_image_urls_absent_sends_all() -> None:
    item = _item_with_images({"title": False})
    fake = _FakeXano()
    XanoTillinDestination(fake).apply(item)  # type: ignore[arg-type]

    assert fake.images == (1911, ["https://a.jpg", "https://b.jpg", "https://c.jpg"])


def test_apply_images_false_overrides_image_urls() -> None:
    item = _item_with_images({"images": False, "image_urls": ["https://a.jpg"]})
    fake = _FakeXano()
    XanoTillinDestination(fake).apply(item)  # type: ignore[arg-type]

    assert fake.images is None


def _weight_item(apply_fields: dict[str, Any] | None) -> EnrichmentItem:
    return EnrichmentItem(
        job_id=1,
        account_id=1,
        tillin_product_id=1911,
        status="approved",
        staged_weights_json=[
            {"variant_id": 1, "weight": 0.4, "weight_unit": "kg"},
            {"variant_id": 2, "weight": 0.5, "weight_unit": "kg"},
        ],
        apply_fields_json=apply_fields,
    )


def test_apply_weight_sends_first_selected_at_product_level() -> None:
    # /product/weight is product-level: the first selected proposal wins
    # (variant 2 -> 0.5 kg -> unit code "1"); no copy/image write here.
    item = _weight_item({"weights": True, "weight_variant_ids": [2]})
    fake = _FakeXano()
    XanoTillinDestination(fake).apply(item)  # type: ignore[arg-type]

    assert fake.weight == ([1911], 0.5, "1")
    assert fake.images is None
    assert fake.enrich is None


def test_apply_weight_absent_selection_uses_first_staged() -> None:
    item = _weight_item({"title": False})  # no weight selection -> all -> first
    fake = _FakeXano()
    XanoTillinDestination(fake).apply(item)  # type: ignore[arg-type]

    assert fake.weight == ([1911], 0.4, "1")


def test_apply_weights_false_sends_no_weight() -> None:
    item = _weight_item({"weights": False})
    fake = _FakeXano()
    XanoTillinDestination(fake).apply(item)  # type: ignore[arg-type]

    assert fake.weight is None


def test_apply_weight_empty_selection_sends_no_weight() -> None:
    item = _weight_item({"weight_variant_ids": []})
    fake = _FakeXano()
    XanoTillinDestination(fake).apply(item)  # type: ignore[arg-type]

    assert fake.weight is None


def test_selected_weights_filters_by_variant_id() -> None:
    staged = [
        {"variant_id": 1, "weight": 0.4, "weight_unit": "kg"},
        {"variant_id": 2, "weight": 0.5, "weight_unit": "kg"},
        {"variant_id": 3, "weight": 0.6, "weight_unit": "kg"},
    ]
    # Absent selection -> all; subset -> filtered; empty -> none; unknown ignored.
    assert _selected_weights(staged, None) == staged
    assert _selected_weights(staged, [3, 1, 999]) == [staged[0], staged[2]]
    assert _selected_weights(staged, []) == []
    assert _selected_weights(None, [1]) == []


# ---------------------------------------------------------------------------
# Normalized entries (asset_id) — staged bytes uploaded via the bulk endpoint.
# ---------------------------------------------------------------------------

NORMALIZED_BYTES = b"normalized-webp-bytes"
RAW_URL = "https://raw.example/2.jpg"


@pytest.fixture
def staged_db(
    db_session_factory: sessionmaker[Session],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> Session:
    monkeypatch.setattr(settings, "IMAGING_DIR", str(tmp_path / "imaging"))
    return db_session_factory()


def _seed_normalized_item(
    db: Session,
    *,
    with_file: bool = True,
    apply_fields: dict[str, Any] | None = None,
) -> tuple[EnrichmentItem, ImageAsset]:
    """One approved item: entry 1 normalized (asset-backed), entry 2 raw URL."""
    account = Account(name="default")
    db.add(account)
    db.flush()
    job = EnrichmentJob(account_id=account.id, selection_json={}, config_json={})
    db.add(job)
    db.flush()
    item = EnrichmentItem(
        job_id=job.id,
        account_id=account.id,
        tillin_product_id=1911,
        status="approved",
        apply_fields_json=apply_fields,
    )
    asset = ImageAsset(
        account_id=account.id,
        product_id=1911,
        verb="normalize",
        provider="photoroom",
        status="completed",
        source_image="https://src.example/1.jpg",
    )
    db.add_all([item, asset])
    db.flush()
    if with_file:
        asset.staged_paths_json = [staging.store(asset.id, 0, NORMALIZED_BYTES, "webp")]
    else:
        asset.staged_paths_json = [f"{asset.id}/0.webp"]  # purged/never written
    item.staged_images_json = [
        {
            "url": f"/imaging/assets/{asset.id}/files/0",
            "position": 1,
            "asset_id": asset.id,
            "source_url": "https://src.example/1.jpg",
        },
        {"url": RAW_URL, "position": 2},
    ]
    db.commit()
    return item, asset


def test_apply_uploads_normalized_bytes_and_adds_raw_urls(staged_db: Session) -> None:
    item, asset = _seed_normalized_item(staged_db)
    fake = _FakeXano()
    XanoTillinDestination(fake).apply(item)  # type: ignore[arg-type]

    # Raw entry still goes through the URL bulk; normalized one as bytes.
    assert fake.images == (1911, [RAW_URL])
    assert fake.uploads == (
        1911,
        [(f"normalize_{asset.id}_1.webp", NORMALIZED_BYTES, "image/webp")],
    )
    # The created Tillin image id is traced on the asset, staging is purged.
    assert asset.tillin_image_ids_json == [9000]
    with pytest.raises(FileNotFoundError):
        staging.load(f"{asset.id}/0.webp")


def test_apply_selection_keeps_only_selected_normalized_entry(
    staged_db: Session,
) -> None:
    item, asset = _seed_normalized_item(staged_db)
    item.apply_fields_json = {"image_urls": [f"/imaging/assets/{asset.id}/files/0"]}
    staged_db.commit()
    fake = _FakeXano()
    XanoTillinDestination(fake).apply(item)  # type: ignore[arg-type]

    assert fake.images is None  # raw entry dropped by the reviewer
    assert fake.uploads is not None
    assert [part[0] for part in fake.uploads[1]] == [f"normalize_{asset.id}_1.webp"]


def test_apply_selection_keeps_only_raw_entry(staged_db: Session) -> None:
    item, asset = _seed_normalized_item(
        staged_db, apply_fields={"image_urls": [RAW_URL]}
    )
    fake = _FakeXano()
    XanoTillinDestination(fake).apply(item)  # type: ignore[arg-type]

    assert fake.images == (1911, [RAW_URL])
    assert fake.uploads is None
    # Untouched asset: staging is still there, no Tillin id recorded.
    assert staging.load(f"{asset.id}/0.webp") == NORMALIZED_BYTES
    assert asset.tillin_image_ids_json is None


def test_apply_missing_staged_file_fails_before_any_write(staged_db: Session) -> None:
    item, _asset = _seed_normalized_item(staged_db, with_file=False)
    fake = _FakeXano()
    with pytest.raises(AppException) as excinfo:
        XanoTillinDestination(fake).apply(item)  # type: ignore[arg-type]

    assert excinfo.value.code == "staging_missing"
    # Bytes are loaded before any write: nothing was pushed, not even raw URLs.
    assert fake.images is None
    assert fake.uploads is None


def test_apply_without_images_only_enriches() -> None:
    item = EnrichmentItem(
        job_id=1,
        account_id=1,
        tillin_product_id=42,
        status="approved",
        staged_description="Desc",
    )
    fake = _FakeXano()
    XanoTillinDestination(fake).apply(item)  # type: ignore[arg-type]

    assert fake.images is None
    assert fake.enrich is not None
    assert fake.enrich["description"] == "Desc"
