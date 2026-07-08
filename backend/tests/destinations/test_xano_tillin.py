"""Unit test for the Tillin destination adapter (staged fields -> writes)."""

from typing import Any

from app.destinations.xano_tillin import XanoTillinDestination, _selected_weights
from app.models import EnrichmentItem


class _FakeXano:
    def __init__(self) -> None:
        self.images: tuple[int, list[str]] | None = None
        self.enrich: dict[str, Any] | None = None

    def add_product_images(self, product_id: int, image_urls: list[str]) -> None:
        self.images = (product_id, image_urls)

    def enrich_product(self, product_id: int, **kwargs: Any) -> None:
        self.enrich = {"product_id": product_id, **kwargs}


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


def test_apply_weight_selection_sends_nothing_yet() -> None:
    # Weights writeback awaits the Xano set_variant_weights endpoint: the
    # selection keys must be accepted without triggering any write.
    item = EnrichmentItem(
        job_id=1,
        account_id=1,
        tillin_product_id=1911,
        status="approved",
        staged_weights_json=[
            {"variant_id": 1, "weight": 0.4, "weight_unit": "kg"},
            {"variant_id": 2, "weight": 0.5, "weight_unit": "kg"},
        ],
        apply_fields_json={"weights": True, "weight_variant_ids": [2]},
    )
    fake = _FakeXano()
    XanoTillinDestination(fake).apply(item)  # type: ignore[arg-type]

    assert fake.images is None
    assert fake.enrich is None


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
