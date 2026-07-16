"""Tests for the composed enrichment pipeline (worker processor)."""

import json
from pathlib import Path
from typing import Any

import httpx
import pytest
from sqlalchemy.orm import Session, sessionmaker

import app.imaging.service as imaging_service
from app.api.schemas import Brand, Product, ProductVariant
from app.clients.claude import ClaudeUsage, CopyResult
from app.clients.firecrawl import FirecrawlClient
from app.clients.photoroom import PhotoroomClient
from app.core.config import settings
from app.enrich.pipeline import EnrichmentPipeline
from app.imaging import staging
from app.imaging.compose import probe
from app.jobs.worker import process_one
from app.models import Account, EnrichmentItem, EnrichmentJob, ImageAsset, UsageEvent
from tests.images import cutout_png, source_jpeg

SITE = "https://gramicci.example"

PRODUCT = Product(
    id=101,
    title="G-Short Double Navy",
    reference_code="G5FU-T081",
    brand=Brand(id=7, name="Gramicci", website_urls=[SITE]),
    season="SS25",
    variants=[
        ProductVariant(id=11, sku="TIL-001", barcode="4550479812345"),
        ProductVariant(id=12, sku="TIL-002", barcode="4550479812352"),
    ],
)

SOURCE_PRODUCT = {
    "title": "G-Short Double Navy",
    "handle": "g-short-double-navy",
    "tags": "shorts, ss25",
    "body_html": "<p>Le short d'origine.</p>",
    "variants": [
        {"sku": "G5FU-T081-M", "barcode": "4550479812345", "grams": 320},
        {"sku": "G5FU-T081-L", "barcode": "4550479812352", "grams": 340},
    ],
    "images": [
        {"src": f"{SITE}/cdn/1.jpg"},
        {"src": f"{SITE}/cdn/2.jpg"},
    ],
}


def _store(catalog: dict[str, dict[str, Any]]) -> httpx.MockTransport:
    """Fake Shopify store (same shape as the resolver tests)."""

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path == "/search/suggest.json":
            query = request.url.params["q"].lower()
            hits = [
                {"handle": handle, "title": product["title"]}
                for handle, product in catalog.items()
                if query in product["title"].lower()
                or any(
                    query == str(v.get("barcode", "")).lower()
                    for v in product["variants"]
                )
            ]
            return httpx.Response(
                200, json={"resources": {"results": {"products": hits}}}
            )
        if path.startswith("/products/") and path.endswith(".json"):
            handle = path.removeprefix("/products/").removesuffix(".json")
            if handle in catalog:
                return httpx.Response(200, json={"product": catalog[handle]})
            return httpx.Response(404)
        return httpx.Response(404)

    return httpx.MockTransport(handler)


def _seed_item(
    db: Session, product_id: int, config: dict[str, Any] | None = None
) -> EnrichmentItem:
    account = Account(name="default")
    db.add(account)
    db.flush()
    job = EnrichmentJob(
        account_id=account.id, selection_json={}, config_json=config or {}
    )
    db.add(job)
    db.flush()
    item = EnrichmentItem(
        job_id=job.id, account_id=account.id, tillin_product_id=product_id
    )
    db.add(item)
    db.commit()
    db.refresh(item)
    return item


class _FakeClaude:
    """Stands in for ClaudeClient.generate_copy."""

    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    def generate_copy(
        self,
        product_ctx: dict[str, Any],
        *,
        editorial_instructions: str = "",
        model: str | None = None,
        meta_max_length: int = 160,
    ) -> Any:
        self.calls.append(
            {
                "ctx": product_ctx,
                "instructions": editorial_instructions,
                "model": model,
                "meta_max_length": meta_max_length,
            }
        )
        return CopyResult(
            description_fr="Un short robuste et léger.",
            meta_description_fr="Short Gramicci G-Short — confort et style.",
            usage=ClaudeUsage(
                model="claude-test-1", input_tokens=321, output_tokens=87
            ),
        )


def test_pipeline_stages_title_weights_images_and_copy(
    db_session_factory: sessionmaker[Session],
) -> None:
    db = db_session_factory()
    item = _seed_item(db, PRODUCT.id)
    claude = _FakeClaude()

    with httpx.Client(
        transport=_store({"g-short-double-navy": SOURCE_PRODUCT})
    ) as http_client:
        pipeline = EnrichmentPipeline(
            read_product=lambda _pid, _account: PRODUCT,
            http_client=http_client,
            claude=claude,  # type: ignore[arg-type]
        )
        assert process_one(db, pipeline) is True

    db.refresh(item)
    assert item.status == "ready_for_review"
    # Default template is {title} — the brand is not prepended anymore.
    assert item.staged_title == "G-Short Double Navy"
    assert item.source_url == f"{SITE}/products/g-short-double-navy"
    assert item.source_method == "shopify_json"
    assert item.match_score == 1.0
    assert item.staged_weights_json == [
        {"variant_id": 11, "weight": 0.32, "weight_unit": "kg"},
        {"variant_id": 12, "weight": 0.34, "weight_unit": "kg"},
    ]
    assert item.staged_images_json == [
        {"url": f"{SITE}/cdn/1.jpg", "position": 1},
        {"url": f"{SITE}/cdn/2.jpg", "position": 2},
    ]
    assert item.staged_description == "Un short robuste et léger."
    assert item.staged_meta is not None
    # The copywriter saw both canonical and source-page facts.
    assert claude.calls[0]["ctx"]["brand"] == "Gramicci"
    assert "source_description_html" in claude.calls[0]["ctx"]

    # Metering (M1): the Claude call left one event per token metric.
    events = db.query(UsageEvent).order_by(UsageEvent.id).all()
    assert [(e.metric, e.quantity) for e in events] == [
        ("input_tokens", 321),
        ("output_tokens", 87),
    ]
    assert all(
        (e.source, e.provider, e.model) == ("enrichment", "claude", "claude-test-1")
        for e in events
    )
    assert all(
        (e.account_id, e.job_id, e.item_id) == (item.account_id, item.job_id, item.id)
        for e in events
    )
    db.close()


def test_pipeline_without_claude_and_without_brand_site(
    db_session_factory: sessionmaker[Session],
) -> None:
    """Degraded mode: no AI key, product without brand website."""
    db = db_session_factory()
    item = _seed_item(db, 999, config={"title_template": "{brand} {title} {season}"})
    bare = Product(id=999, title="Produit 999")

    with httpx.Client(transport=_store({})) as http_client:
        pipeline = EnrichmentPipeline(
            read_product=lambda _pid, _account: bare, http_client=http_client
        )
        assert process_one(db, pipeline) is True

    db.refresh(item)
    assert item.status == "ready_for_review"
    assert item.staged_title == "Produit 999"  # empty tokens collapse
    assert item.source_method == "skipped"
    assert item.source_url is None
    assert item.staged_description is None
    assert item.staged_weights_json is None
    db.close()


def test_pipeline_persists_resolution_candidates(
    db_session_factory: sessionmaker[Session],
) -> None:
    db = db_session_factory()
    item = _seed_item(db, PRODUCT.id)

    with httpx.Client(
        transport=_store({"g-short-double-navy": SOURCE_PRODUCT})
    ) as http_client:
        pipeline = EnrichmentPipeline(
            read_product=lambda _pid, _account: PRODUCT, http_client=http_client
        )
        assert process_one(db, pipeline) is True

    db.refresh(item)
    assert item.resolution_json is not None
    candidates = item.resolution_json["candidates"]
    assert candidates and candidates[0]["score"] == 1.0
    assert candidates[0]["url"] == f"{SITE}/products/g-short-double-navy"
    db.close()


def test_stage_from_url_manually_restages(
    db_session_factory: sessionmaker[Session],
) -> None:
    db = db_session_factory()
    item = _seed_item(db, PRODUCT.id)
    item.status = "ready_for_review"
    item.source_method = "needs_manual"
    db.commit()
    claude = _FakeClaude()

    with httpx.Client(
        transport=_store({"g-short-double-navy": SOURCE_PRODUCT})
    ) as http_client:
        pipeline = EnrichmentPipeline(
            read_product=lambda _pid, _account: PRODUCT,
            http_client=http_client,
            claude=claude,  # type: ignore[arg-type]
        )
        pipeline.stage_from_url(item, f"{SITE}/products/g-short-double-navy")

    db.commit()
    db.refresh(item)
    assert item.source_method == "manual"
    assert item.source_url == f"{SITE}/products/g-short-double-navy"
    assert item.match_score == 1.0
    assert item.staged_images_json == [
        {"url": f"{SITE}/cdn/1.jpg", "position": 1},
        {"url": f"{SITE}/cdn/2.jpg", "position": 2},
    ]
    assert item.staged_description == "Un short robuste et léger."
    db.close()


def test_pipeline_reaches_extra_website_urls(
    db_session_factory: sessionmaker[Session],
) -> None:
    """A job's extra sources are tried even when the brand has no website."""
    db = db_session_factory()
    product = Product(
        id=PRODUCT.id,
        title=PRODUCT.title,
        reference_code=PRODUCT.reference_code,
        brand=Brand(id=7, name="Gramicci"),  # no website_urls
        season=PRODUCT.season,
        variants=PRODUCT.variants,
    )
    item = _seed_item(
        db,
        product.id,
        config={"extra_website_urls": ["  ", f"{SITE}", f"{SITE}/"]},
    )

    with httpx.Client(
        transport=_store({"g-short-double-navy": SOURCE_PRODUCT})
    ) as http_client:
        pipeline = EnrichmentPipeline(
            read_product=lambda _pid, _account: product, http_client=http_client
        )
        assert process_one(db, pipeline) is True

    db.refresh(item)
    assert item.source_url == f"{SITE}/products/g-short-double-navy"
    assert item.source_method == "shopify_json"
    db.close()


def test_pipeline_passes_context_keywords_and_meta_length_to_claude(
    db_session_factory: sessionmaker[Session],
) -> None:
    db = db_session_factory()
    _seed_item(
        db,
        PRODUCT.id,
        config={
            "editorial_instructions": "Ton sobre.",
            "client_context": "Boutique lyonnaise, mode responsable.",
            "seo_keywords": ["short homme", "gramicci"],
            "meta_max_length": 140,
        },
    )
    claude = _FakeClaude()

    with httpx.Client(
        transport=_store({"g-short-double-navy": SOURCE_PRODUCT})
    ) as http_client:
        pipeline = EnrichmentPipeline(
            read_product=lambda _pid, _account: PRODUCT,
            http_client=http_client,
            claude=claude,  # type: ignore[arg-type]
        )
        assert process_one(db, pipeline) is True

    call = claude.calls[0]
    # The boutique context is prefixed before the job's instructions.
    assert call["instructions"] == (
        "Contexte boutique :\nBoutique lyonnaise, mode responsable.\n\nTon sobre."
    )
    assert call["ctx"]["seo_keywords"] == ["short homme", "gramicci"]
    assert call["meta_max_length"] == 140
    db.close()


def test_pipeline_selects_instruction_by_product_category(
    db_session_factory: sessionmaker[Session],
) -> None:
    db = db_session_factory()
    product = Product(
        id=PRODUCT.id,
        title=PRODUCT.title,
        reference_code=PRODUCT.reference_code,
        brand=PRODUCT.brand,
        season=PRODUCT.season,
        category="Shorts",
        variants=PRODUCT.variants,
    )
    _seed_item(
        db,
        product.id,
        config={
            "category_instructions": {
                "Shorts": "Parle de la coupe.",
                "Polos": "Parle du col.",
            }
        },
    )
    claude = _FakeClaude()

    with httpx.Client(
        transport=_store({"g-short-double-navy": SOURCE_PRODUCT})
    ) as http_client:
        pipeline = EnrichmentPipeline(
            read_product=lambda _pid, _account: product,
            http_client=http_client,
            claude=claude,  # type: ignore[arg-type]
        )
        assert process_one(db, pipeline) is True

    # The product's category picks its snapshotted instruction; defaults hold.
    assert claude.calls[0]["instructions"] == "Parle de la coupe."
    assert claude.calls[0]["meta_max_length"] == 160
    db.close()


# ---------------------------------------------------------------------------
# Transform toggles (config_json["transforms"]) — absent block/key = enabled.
# ---------------------------------------------------------------------------


def _run(
    db: Session,
    *,
    claude: _FakeClaude | None = None,
    photoroom: PhotoroomClient | None = None,
) -> None:
    with httpx.Client(
        transport=_store({"g-short-double-navy": SOURCE_PRODUCT})
    ) as http_client:
        pipeline = EnrichmentPipeline(
            read_product=lambda _pid, _account: PRODUCT,
            http_client=http_client,
            claude=claude,  # type: ignore[arg-type]
            photoroom=photoroom,
        )
        assert process_one(db, pipeline) is True


def test_transforms_all_disabled_stages_nothing_but_reaches_review(
    db_session_factory: sessionmaker[Session],
) -> None:
    db = db_session_factory()
    item = _seed_item(
        db,
        PRODUCT.id,
        config={
            "transforms": {
                "copy": False,
                "title": False,
                "weights": False,
                "images": False,
            }
        },
    )
    claude = _FakeClaude()
    _run(db, claude=claude)

    db.refresh(item)
    assert item.status == "ready_for_review"  # degenerate case: nothing staged
    assert item.staged_title is None
    assert item.source_url is None  # source resolution skipped entirely
    assert item.source_method is None
    assert item.staged_weights_json is None
    assert item.staged_images_json is None
    assert item.staged_description is None
    assert item.staged_meta is None
    assert claude.calls == []
    db.close()


def test_transforms_title_only_skips_source_resolution(
    db_session_factory: sessionmaker[Session],
) -> None:
    """Title does not depend on the source: resolution must not even run."""
    db = db_session_factory()
    item = _seed_item(
        db,
        PRODUCT.id,
        config={"transforms": {"copy": False, "weights": False, "images": False}},
    )
    _run(db)

    db.refresh(item)
    assert item.staged_title == "G-Short Double Navy"
    assert item.source_url is None
    assert item.staged_weights_json is None
    assert item.staged_images_json is None
    db.close()


@pytest.mark.parametrize("disabled", ["copy", "title", "weights", "images"])
def test_transforms_single_toggle_disables_only_its_field(
    db_session_factory: sessionmaker[Session], disabled: str
) -> None:
    db = db_session_factory()
    item = _seed_item(db, PRODUCT.id, config={"transforms": {disabled: False}})
    claude = _FakeClaude()
    _run(db, claude=claude)

    db.refresh(item)
    assert item.status == "ready_for_review"
    assert (item.staged_title is None) == (disabled == "title")
    assert (item.staged_weights_json is None) == (disabled == "weights")
    assert (item.staged_images_json is None) == (disabled == "images")
    assert (item.staged_description is None) == (disabled == "copy")
    assert (claude.calls == []) == (disabled == "copy")
    # The other transforms still depend on the source: it resolved.
    assert item.source_url == f"{SITE}/products/g-short-double-navy"
    db.close()


def test_transforms_empty_block_means_all_enabled(
    db_session_factory: sessionmaker[Session],
) -> None:
    db = db_session_factory()
    item = _seed_item(db, PRODUCT.id, config={"transforms": {}})
    claude = _FakeClaude()
    _run(db, claude=claude)

    db.refresh(item)
    assert item.staged_title is not None
    assert item.staged_weights_json is not None
    assert item.staged_images_json is not None
    assert item.staged_description is not None
    db.close()


# ---------------------------------------------------------------------------
# Batch image normalization (Photoroom) — assets, staging, metering, fallback.
# ---------------------------------------------------------------------------


@pytest.fixture
def imaging_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    directory = tmp_path / "imaging"
    monkeypatch.setattr(settings, "IMAGING_DIR", str(directory))
    return directory


def _photoroom(handler: Any) -> PhotoroomClient:
    return PhotoroomClient("pr-key", transport=httpx.MockTransport(handler))


@pytest.mark.usefixtures("imaging_dir")
def test_pipeline_normalizes_source_images_with_photoroom(
    db_session_factory: sessionmaker[Session],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db = db_session_factory()
    item = _seed_item(
        db,
        PRODUCT.id,
        # Originals are the default since 2026-07-10; batch normalization is
        # an explicit opt-in.
        config={"image": {"bg_color": "F5F5F5", "quality": 90, "auto_normalize": True}},
    )
    monkeypatch.setattr(imaging_service, "_download_source", lambda url: source_jpeg())
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, content=cutout_png())

    _run(db, photoroom=_photoroom(handler))

    db.refresh(item)
    assets = db.query(ImageAsset).order_by(ImageAsset.id).all()
    assert len(assets) == 2
    assert item.staged_images_json == [
        {
            "url": f"/imaging/assets/{assets[0].id}/files/0",
            "position": 1,
            "asset_id": assets[0].id,
            "source_url": f"{SITE}/cdn/1.jpg",
        },
        {
            "url": f"/imaging/assets/{assets[1].id}/files/0",
            "position": 2,
            "asset_id": assets[1].id,
            "source_url": f"{SITE}/cdn/2.jpg",
        },
    ]
    for asset, source in zip(assets, ("1.jpg", "2.jpg"), strict=True):
        assert (asset.verb, asset.provider, asset.status) == (
            "normalize",
            "photoroom",
            "completed",
        )
        assert asset.product_id == PRODUCT.id
        assert asset.account_id == item.account_id
        assert asset.source_image == f"{SITE}/cdn/{source}"
        assert asset.params_json["options"]["bg_color"] == "F5F5F5"
        assert asset.params_json["trace"]["provider"] == "photoroom"
        # The composed output is staged on disk under the asset id (real 4:5).
        assert probe(staging.load(asset.staged_paths_json[0])) == (
            1600,
            2000,
            "webp",
        )
        # The job options reached the compose step.
        assert asset.params_json["trace"]["params"]["quality"] == 90
    # One segment call per image, on the sdk host (multipart POST).
    assert [
        (request.method, request.url.host, request.url.path) for request in seen
    ] == [("POST", "sdk.photoroom.com", "/v1/segment")] * 2

    # Metering: one photoroom event per image, tied to the job and item.
    events = [
        e
        for e in db.query(UsageEvent).order_by(UsageEvent.id)
        if e.provider == "photoroom"
    ]
    assert [(e.metric, e.quantity) for e in events] == [("images", 1), ("images", 1)]
    assert all(
        (e.source, e.job_id, e.item_id) == ("imaging", item.job_id, item.id)
        for e in events
    )
    db.close()


@pytest.mark.usefixtures("imaging_dir")
def test_pipeline_normalization_failure_falls_back_to_raw_url(
    db_session_factory: sessionmaker[Session],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """One image failing keeps its raw URL; the others stay normalized."""
    db = db_session_factory()
    item = _seed_item(db, PRODUCT.id, config={"image": {"auto_normalize": True}})

    def fake_download(url: str) -> bytes:
        if "1.jpg" in url:
            raise RuntimeError("source unreachable")
        return source_jpeg()

    monkeypatch.setattr(imaging_service, "_download_source", fake_download)
    _run(db, photoroom=_photoroom(lambda r: httpx.Response(200, content=cutout_png())))

    db.refresh(item)
    assets = db.query(ImageAsset).order_by(ImageAsset.id).all()
    assert [a.status for a in assets] == ["failed", "completed"]
    assert assets[0].error
    completed = assets[1]
    assert item.staged_images_json == [
        {"url": f"{SITE}/cdn/1.jpg", "position": 1},  # raw fallback
        {
            "url": f"/imaging/assets/{completed.id}/files/0",
            "position": 2,
            "asset_id": completed.id,
            "source_url": f"{SITE}/cdn/2.jpg",
        },
    ]
    # Only the successful normalization was metered.
    photoroom_events = [
        e for e in db.query(UsageEvent).all() if e.provider == "photoroom"
    ]
    assert len(photoroom_events) == 1
    db.close()


def test_pipeline_without_photoroom_stages_raw_urls(
    db_session_factory: sessionmaker[Session],
) -> None:
    """No Photoroom client (key missing) → same raw-URL staging as before."""
    db = db_session_factory()
    item = _seed_item(db, PRODUCT.id)
    _run(db)

    db.refresh(item)
    assert item.staged_images_json == [
        {"url": f"{SITE}/cdn/1.jpg", "position": 1},
        {"url": f"{SITE}/cdn/2.jpg", "position": 2},
    ]
    assert db.query(ImageAsset).count() == 0
    db.close()


# ---------------------------------------------------------------------------
# Firecrawl fallback (plan Phase 3) — non-Shopify sites, manual URLs, metering.
# ---------------------------------------------------------------------------

NON_SHOPIFY_SITE = "https://salomon.example"

FIRECRAWL_PAGE = {
    "title": "G-Short Double Navy",
    "description": "Ref. G5FU-T081 — le short d'origine.",
    "images": [f"{NON_SHOPIFY_SITE}/img/1.jpg", f"{NON_SHOPIFY_SITE}/img/2.jpg"],
    "reference_codes": ["G5FU-T081"],
}

NON_SHOPIFY_PRODUCT = PRODUCT.model_copy(
    update={"brand": Brand(id=8, name="Salomon", website_urls=[NON_SHOPIFY_SITE])}
)


def _firecrawl_store(pages: dict[str, dict[str, Any]]) -> FirecrawlClient:
    """Fake Firecrawl (same shape as the resolver tests)."""

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        if request.url.path == "/v2/search":
            host = body["query"].split()[0].removeprefix("site:")
            hits = [
                {"url": url, "title": page.get("title")}
                for url, page in pages.items()
                if httpx.URL(url).host == host
            ]
            return httpx.Response(200, json={"success": True, "data": {"web": hits}})
        if request.url.path == "/v2/scrape":
            page = pages.get(body["url"])
            data: dict[str, Any] = {"metadata": {}}
            if page is not None:
                data["json"] = page
            return httpx.Response(200, json={"success": True, "data": data})
        return httpx.Response(404)

    return FirecrawlClient("fc-key", transport=httpx.MockTransport(handler))


def _forbidden_firecrawl() -> FirecrawlClient:
    def handler(_request: httpx.Request) -> httpx.Response:
        raise AssertionError("firecrawl must not be called")

    return FirecrawlClient("fc-key", transport=httpx.MockTransport(handler))


@pytest.mark.usefixtures("imaging_dir")
def test_pipeline_firecrawl_fallback_end_to_end(
    db_session_factory: sessionmaker[Session],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Shopify KO on a non-Shopify site → firecrawl resolves, images are
    normalized from the extracted URLs, copy sees the source description."""
    db = db_session_factory()
    item = _seed_item(db, PRODUCT.id, config={"image": {"auto_normalize": True}})
    claude = _FakeClaude()
    monkeypatch.setattr(imaging_service, "_download_source", lambda url: source_jpeg())

    def photoroom_handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=cutout_png())

    with (
        httpx.Client(transport=_store({})) as http_client,  # suggest.json empty
        _firecrawl_store({f"{NON_SHOPIFY_SITE}/fiche/g-short": FIRECRAWL_PAGE}) as fc,
    ):
        pipeline = EnrichmentPipeline(
            read_product=lambda _pid, _account: NON_SHOPIFY_PRODUCT,
            http_client=http_client,
            claude=claude,  # type: ignore[arg-type]
            photoroom=_photoroom(photoroom_handler),
            firecrawl=fc,
        )
        assert process_one(db, pipeline) is True

    db.refresh(item)
    assert item.status == "ready_for_review"
    assert item.source_method == "firecrawl"
    assert item.source_url == f"{NON_SHOPIFY_SITE}/fiche/g-short"
    assert item.match_score == 0.9
    # A scraped page carries no variant data: no weight proposals.
    assert item.staged_weights_json is None
    # Images were normalized straight from the extracted URLs (no refetch).
    assets = db.query(ImageAsset).order_by(ImageAsset.id).all()
    assert [a.source_image for a in assets] == [
        f"{NON_SHOPIFY_SITE}/img/1.jpg",
        f"{NON_SHOPIFY_SITE}/img/2.jpg",
    ]
    assert item.staged_images_json is not None
    assert [e["source_url"] for e in item.staged_images_json] == [
        f"{NON_SHOPIFY_SITE}/img/1.jpg",
        f"{NON_SHOPIFY_SITE}/img/2.jpg",
    ]
    # The copywriter saw the extracted description as the source description.
    assert claude.calls[0]["ctx"]["source_description_html"] == (
        "Ref. G5FU-T081 — le short d'origine."
    )
    assert item.staged_description == "Un short robuste et léger."

    # Metering: firecrawl credits (search=2 then extract=5) tied to job/item.
    fc_events = [
        e
        for e in db.query(UsageEvent).order_by(UsageEvent.id)
        if e.provider == "firecrawl"
    ]
    assert [(e.metric, e.quantity) for e in fc_events] == [
        ("credits", 2),
        ("credits", 5),
    ]
    assert all(
        (e.source, e.account_id, e.job_id, e.item_id)
        == ("enrichment", item.account_id, item.job_id, item.id)
        for e in fc_events
    )
    db.close()


def test_stage_from_url_non_shopify_falls_back_to_firecrawl(
    db_session_factory: sessionmaker[Session],
) -> None:
    db = db_session_factory()
    item = _seed_item(db, PRODUCT.id)
    item.status = "ready_for_review"
    db.commit()
    url = f"{NON_SHOPIFY_SITE}/fiche/g-short"  # no /products/ segment

    with (
        httpx.Client(transport=_store({})) as http_client,
        _firecrawl_store({url: FIRECRAWL_PAGE}) as fc,
    ):
        pipeline = EnrichmentPipeline(
            read_product=lambda _pid, _account: NON_SHOPIFY_PRODUCT,
            http_client=http_client,
            firecrawl=fc,
        )
        pipeline.stage_from_url(item, url)

    db.commit()
    db.refresh(item)
    assert item.source_method == "manual"
    assert item.source_url == url
    assert item.match_score == 0.9  # the extracted page carries the reference
    assert item.staged_images_json == [
        {"url": f"{NON_SHOPIFY_SITE}/img/1.jpg", "position": 1},
        {"url": f"{NON_SHOPIFY_SITE}/img/2.jpg", "position": 2},
    ]
    fc_events = [e for e in db.query(UsageEvent).all() if e.provider == "firecrawl"]
    assert [(e.metric, e.quantity, e.item_id) for e in fc_events] == [
        ("credits", 5, item.id)
    ]
    db.close()


def test_stage_images_dedupes_duplicate_source_urls(
    db_session_factory: sessionmaker[Session],
) -> None:
    """LLM extraction can repeat an image URL (seen live on salomon.com) —
    each duplicate would cost a Photoroom normalization, so dedupe first."""
    db = db_session_factory()
    item = _seed_item(db, PRODUCT.id)
    item.status = "ready_for_review"
    db.commit()
    url = f"{NON_SHOPIFY_SITE}/fiche/g-short"
    page = {
        **FIRECRAWL_PAGE,
        "images": [
            f"{NON_SHOPIFY_SITE}/img/1.jpg",
            f"{NON_SHOPIFY_SITE}/img/1.jpg",
            f"{NON_SHOPIFY_SITE}/img/2.jpg",
        ],
    }

    with (
        httpx.Client(transport=_store({})) as http_client,
        _firecrawl_store({url: page}) as fc,
    ):
        pipeline = EnrichmentPipeline(
            read_product=lambda _pid, _account: NON_SHOPIFY_PRODUCT,
            http_client=http_client,
            firecrawl=fc,
        )
        pipeline.stage_from_url(item, url)

    db.commit()
    db.refresh(item)
    assert item.staged_images_json == [
        {"url": f"{NON_SHOPIFY_SITE}/img/1.jpg", "position": 1},
        {"url": f"{NON_SHOPIFY_SITE}/img/2.jpg", "position": 2},
    ]
    db.close()


def test_stage_from_url_firecrawl_low_score_without_reference(
    db_session_factory: sessionmaker[Session],
) -> None:
    db = db_session_factory()
    item = _seed_item(db, PRODUCT.id)
    url = f"{NON_SHOPIFY_SITE}/fiche/autre"
    decoy = {**FIRECRAWL_PAGE, "reference_codes": [], "description": "Autre produit."}

    with (
        httpx.Client(transport=_store({})) as http_client,
        _firecrawl_store({url: decoy}) as fc,
    ):
        pipeline = EnrichmentPipeline(
            read_product=lambda _pid, _account: NON_SHOPIFY_PRODUCT,
            http_client=http_client,
            firecrawl=fc,
        )
        pipeline.stage_from_url(item, url)

    assert item.match_score == 0.5
    db.close()


def test_stage_from_url_without_firecrawl_still_raises(
    db_session_factory: sessionmaker[Session],
) -> None:
    db = db_session_factory()
    item = _seed_item(db, PRODUCT.id)

    with httpx.Client(transport=_store({})) as http_client:
        pipeline = EnrichmentPipeline(
            read_product=lambda _pid, _account: NON_SHOPIFY_PRODUCT,
            http_client=http_client,
        )
        with pytest.raises(LookupError):
            pipeline.stage_from_url(item, f"{NON_SHOPIFY_SITE}/fiche/g-short")
    db.close()


def test_scrape_method_shopify_json_never_touches_firecrawl(
    db_session_factory: sessionmaker[Session],
) -> None:
    """`config_json["scrape"]["default_method"] = "shopify_json"` pins the
    chain: no firecrawl call even when resolution fails."""
    db = db_session_factory()
    item = _seed_item(
        db, PRODUCT.id, config={"scrape": {"default_method": "shopify_json"}}
    )

    with (
        httpx.Client(transport=_store({})) as http_client,
        _forbidden_firecrawl() as fc,
    ):
        pipeline = EnrichmentPipeline(
            read_product=lambda _pid, _account: NON_SHOPIFY_PRODUCT,
            http_client=http_client,
            firecrawl=fc,
        )
        assert process_one(db, pipeline) is True

    db.refresh(item)
    assert item.source_method == "needs_manual"
    assert not [e for e in db.query(UsageEvent).all() if e.provider == "firecrawl"]
    db.close()


def test_pipeline_missing_product_fails_item(
    db_session_factory: sessionmaker[Session],
) -> None:
    db = db_session_factory()
    item = _seed_item(db, 404)

    with httpx.Client(transport=_store({})) as http_client:
        pipeline = EnrichmentPipeline(
            read_product=lambda _pid, _account: None, http_client=http_client
        )
        assert process_one(db, pipeline) is True

    db.refresh(item)
    assert item.status == "pending"  # requeued (attempt 1 of MAX_ATTEMPTS)
    assert item.error is not None
    assert "not found" in item.error
    db.close()
