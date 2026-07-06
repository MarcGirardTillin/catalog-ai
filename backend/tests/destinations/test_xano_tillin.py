"""Unit test for the Tillin destination adapter (staged fields -> writes)."""

from typing import Any

from app.destinations.xano_tillin import XanoTillinDestination
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
