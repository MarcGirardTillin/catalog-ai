"""Unit test for the Tillin destination adapter (staged fields -> writes)."""

from pathlib import Path
from typing import Any

import pytest
from sqlalchemy.orm import Session, sessionmaker

import app.destinations.xano_tillin as xano_tillin
from app.api.exceptions import AppException
from app.api.schemas import Product, ProductImage, ProductVariant
from app.clients.base import ExternalServiceError
from app.clients.xano import FilePart
from app.core.config import settings
from app.destinations.xano_tillin import XanoTillinDestination, _selected_weights
from app.imaging import staging
from app.models import Account, EnrichmentItem, EnrichmentJob, ImageAsset
from tests.images import source_jpeg

# Les entrées « URL brute » sont désormais téléchargées par CatalogAI puis
# poussées en octets — le réseau est coupé dans les tests.
SOURCE_BYTES = source_jpeg()


@pytest.fixture(autouse=True)
def _patch_download(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(xano_tillin, "download_source_image", lambda url: SOURCE_BYTES)


class _FakeXano:
    def __init__(self) -> None:
        self.images: tuple[int, list[str]] | None = None
        self.uploads: tuple[int, list[FilePart]] | None = None
        self.enrich: dict[str, Any] | None = None
        self.weight: tuple[list[int], float, str] | None = None
        self.product: Product | None = None  # returned by get_product
        # Simule le refus silencieux de Xano : N derniers fichiers/URLs jetés.
        self.upload_skip = 0
        self.url_skip = 0

    def get_product(self, product_id: int) -> Product | None:
        return self.product

    def add_product_images(
        self, product_id: int, image_urls: list[str]
    ) -> list[ProductImage]:
        self.images = (product_id, image_urls)
        kept = image_urls[: len(image_urls) - self.url_skip]
        return [
            ProductImage(id=8000 + index, url=url) for index, url in enumerate(kept)
        ]

    def upload_product_images(
        self, product_id: int, files: list[FilePart]
    ) -> list[ProductImage]:
        self.uploads = (product_id, files)
        kept = files[: len(files) - self.upload_skip]
        return [
            ProductImage(id=9000 + index, url=f"https://xano.example/{index}.webp")
            for index in range(len(kept))
        ]

    def enrich_product(self, product_id: int, **kwargs: Any) -> None:
        self.enrich = {"product_id": product_id, **kwargs}

    def set_product_weight(
        self, product_ids: list[int], weight: float, weight_unit: str = "1"
    ) -> None:
        self.weight = (product_ids, weight, weight_unit)


def _upload_names(fake: _FakeXano) -> list[str]:
    assert fake.uploads is not None
    return [part[0] for part in fake.uploads[1]]


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
    warnings = XanoTillinDestination(fake).apply(item)  # type: ignore[arg-type]

    # Les URLs brutes sont téléchargées par CatalogAI et poussées en octets
    # (le push par URL laissait Xano échouer en silence — vécu Farfetch).
    assert fake.images is None
    assert fake.uploads == (
        1911,
        [("a.jpg", SOURCE_BYTES, "image/jpeg"), ("b.jpg", SOURCE_BYTES, "image/jpeg")],
    )
    assert warnings == []
    assert fake.enrich == {
        "product_id": 1911,
        "title": "Titre",
        "description": "Desc",
        "description_html": None,
        "meta_description": "Meta",
        "price": None,
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
        "description_html": None,
        "meta_description": "Meta",
        "price": None,
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

    assert _upload_names(fake) == ["a.jpg", "c.jpg"]


def test_apply_image_urls_ignores_unknown_urls() -> None:
    item = _item_with_images({"image_urls": ["https://b.jpg", "https://zzz.jpg"]})
    fake = _FakeXano()
    XanoTillinDestination(fake).apply(item)  # type: ignore[arg-type]

    assert _upload_names(fake) == ["b.jpg"]


def test_apply_image_urls_empty_list_sends_nothing() -> None:
    item = _item_with_images({"image_urls": []})
    fake = _FakeXano()
    XanoTillinDestination(fake).apply(item)  # type: ignore[arg-type]

    assert fake.images is None
    assert fake.uploads is None


def test_apply_image_urls_absent_sends_all() -> None:
    item = _item_with_images({"title": False})
    fake = _FakeXano()
    XanoTillinDestination(fake).apply(item)  # type: ignore[arg-type]

    assert _upload_names(fake) == ["a.jpg", "b.jpg", "c.jpg"]


def test_apply_images_false_overrides_image_urls() -> None:
    item = _item_with_images({"images": False, "image_urls": ["https://a.jpg"]})
    fake = _FakeXano()
    XanoTillinDestination(fake).apply(item)  # type: ignore[arg-type]

    assert fake.images is None
    assert fake.uploads is None


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


def test_apply_uploads_normalized_bytes_and_raw_urls_as_bytes(
    staged_db: Session,
) -> None:
    item, asset = _seed_normalized_item(staged_db)
    fake = _FakeXano()
    warnings = XanoTillinDestination(fake).apply(item)  # type: ignore[arg-type]

    # UN SEUL bulk multipart : l'entrée normalisée garde ses octets stagés,
    # l'URL brute est téléchargée puis poussée en octets elle aussi.
    assert fake.images is None
    assert fake.uploads == (
        1911,
        [
            (f"normalize_{asset.id}_1.webp", NORMALIZED_BYTES, "image/webp"),
            ("2.jpg", SOURCE_BYTES, "image/jpeg"),
        ],
    )
    assert warnings == []
    # The created Tillin image id is traced on the asset, staging is purged.
    assert asset.tillin_image_ids_json == [9000]
    with pytest.raises(FileNotFoundError):
        staging.load(f"{asset.id}/0.webp")


def test_apply_falls_back_to_url_push_when_download_fails(
    staged_db: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    """CDN qui refuse aussi CatalogAI : repli sur l'import par URL côté Xano,
    lui-même vérifié — ici Xano réussit, aucun avertissement."""
    item, _asset = _seed_normalized_item(staged_db)

    def _refuse(_url: str) -> bytes:
        raise ExternalServiceError("source_image", "403")

    monkeypatch.setattr(xano_tillin, "download_source_image", _refuse)
    fake = _FakeXano()
    warnings = XanoTillinDestination(fake).apply(item)  # type: ignore[arg-type]

    assert fake.images == (1911, [RAW_URL])
    assert warnings == []


def test_apply_warns_when_xano_refuses_url_import(
    staged_db: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Ni CatalogAI ni Xano n'arrivent à récupérer l'image : l'apply passe
    mais l'écart est remonté en avertissement (fini les pertes silencieuses)."""
    item, _asset = _seed_normalized_item(staged_db)

    def _refuse(_url: str) -> bytes:
        raise ExternalServiceError("source_image", "403")

    monkeypatch.setattr(xano_tillin, "download_source_image", _refuse)
    fake = _FakeXano()
    fake.url_skip = 1  # Xano « importe » 0 URL sur 1 (réponse 200 amputée)
    warnings = XanoTillinDestination(fake).apply(item)  # type: ignore[arg-type]

    assert warnings == [
        "1 image(s) sur 1 n'ont pas pu être importées par Tillin depuis leur "
        "URL d'origine (site source protégé)"
    ]


def test_apply_warns_and_keeps_staging_when_xano_drops_an_upload(
    staged_db: Session,
) -> None:
    """Xano répond 200 avec moins d'images que de fichiers envoyés :
    avertissement, pas d'appariement d'ids (incertain), staging conservé."""
    item, asset = _seed_normalized_item(staged_db)
    fake = _FakeXano()
    fake.upload_skip = 1
    warnings = XanoTillinDestination(fake).apply(item)  # type: ignore[arg-type]

    assert warnings == ["1 image(s) sur 2 refusée(s) par Tillin à l'upload"]
    assert asset.tillin_image_ids_json is None
    assert staging.load(f"{asset.id}/0.webp") == NORMALIZED_BYTES


def test_apply_uses_image_title_template_for_upload_names(
    staged_db: Session,
) -> None:
    item, _asset = _seed_normalized_item(staged_db)
    account = staged_db.get(Account, item.account_id)
    assert account is not None
    account.settings_json = {"image_title_template": "{reference} {color} {position}"}
    staged_db.commit()
    fake = _FakeXano()
    fake.product = Product(
        id=1911,
        title="G-Short",
        reference_code="G5FU-T081",
        variants=[ProductVariant(id=1, sku="S", color="Navy")],
    )
    XanoTillinDestination(fake).apply(item)  # type: ignore[arg-type]

    # Le modèle de titre d'image nomme TOUTES les entrées (normalisée en
    # .webp stagé, URL brute re-téléchargée en .jpg réel).
    assert _upload_names(fake) == ["g5fu-t081-navy-1.webp", "g5fu-t081-navy-2.jpg"]


def test_apply_template_falls_back_when_product_missing(staged_db: Session) -> None:
    item, asset = _seed_normalized_item(staged_db)
    account = staged_db.get(Account, item.account_id)
    assert account is not None
    account.settings_json = {"image_title_template": "{reference}"}
    staged_db.commit()
    fake = _FakeXano()  # get_product renvoie None
    XanoTillinDestination(fake).apply(item)  # type: ignore[arg-type]

    assert _upload_names(fake) == [f"normalize_{asset.id}_1.webp", "2.jpg"]


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

    assert _upload_names(fake) == ["2.jpg"]  # URL brute téléchargée -> octets
    assert fake.images is None
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


def test_apply_without_staged_weights_falls_back_to_category_default() -> None:
    """Aucune proposition de poids : repli sur le poids par défaut de la
    catégorie (jamais quand le produit a déjà un poids)."""
    item = EnrichmentItem(
        job_id=1, account_id=1, tillin_product_id=1911, status="approved"
    )
    fake = _FakeXano()
    fake.product = Product(
        id=1911,
        title="Ceinture",
        category="Accessoire",
        variants=[ProductVariant(id=1, sku="S")],
    )
    fake.category_weights = {"accessoire": 0.25}  # type: ignore[attr-defined]
    fake.category_default_weights = lambda: fake.category_weights  # type: ignore[attr-defined]
    XanoTillinDestination(fake).apply(item)  # type: ignore[arg-type]

    assert fake.weight == ([1911], 0.25, "1")

    # Produit qui a déjà un poids : rien n'est écrit.
    fake2 = _FakeXano()
    fake2.product = Product(
        id=1911,
        title="Ceinture",
        category="Accessoire",
        variants=[ProductVariant(id=1, sku="S", weight=0.4)],
    )
    fake2.category_default_weights = lambda: {"accessoire": 0.25}  # type: ignore[attr-defined]
    XanoTillinDestination(fake2).apply(item)  # type: ignore[arg-type]
    assert fake2.weight is None
